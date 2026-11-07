"""知识库服务（模块9.1 的 RAG 基础）。

职责分三层：

1. **切块**：法条与律所知识都切成 ≤ ``embedding_max_chars`` 的片段。
   这是硬要求——按 460 字切块是为了让每条分块足够聚焦（检索命中更准），
   同时兼容 TEI 的 512 token 单条上限；超长条文由客户端切块，不能依赖截断
   （法条被截尾会丢失后半段的法律要件，检索到时反而误导模型）。
2. **向量化与写入**：调 :mod:`app.ai.embedding` 批量取向量，upsert 进 Qdrant。
   点 ID 用 ``uuid5(source:id:chunk)`` 生成，**确定性**，重复执行只是覆盖，
   天然幂等。
3. **检索**：query 向量化 → top-k → 回带 payload。供 9.3 RAG 问答调用。

同一条文被切成多块时，``law_article.vector_id`` 记首块的点 ID，其余块靠
payload 里的 ``article_id`` 关联，检索命中即可回表取完整原文。
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PointIdsList,
    PointStruct,
    VectorParams,
)
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import embedding
from app.config import settings
from app.core.exceptions import BadRequest, NotFound
from app.models.kb_document import KbDocument
from app.models.law_article import LawArticle

logger = logging.getLogger(__name__)

# 确定性 UUID 命名空间：只要来源与 ID 不变，重复导入会命中同一个点
_NAMESPACE = uuid.UUID("6f1c5f2e-0f4b-4a4e-9d5c-6b2f8f1e9a10")

# 句读优先级：优先在这里断开，其次才硬切
_BREAKS = "。；！？："
_UPSERT_BATCH = 256

KB_SOURCE_LAW = "law"
KB_SOURCE_FIRM = "firm"

CATEGORY_LABELS = {
    "faq": "常见问题",
    "case_summary": "案件摘要",
    "manual": "办案手册",
}


# ---------------------------------------------------------------------------
# 切块
# ---------------------------------------------------------------------------


def chunk_text(
    text: str,
    *,
    max_chars: int | None = None,
    overlap: int = 60,
) -> list[str]:
    """把长文本切成不超过 ``max_chars`` 的片段。

    切点优先落在句读（。；！？：）上，避免把一句话从中间劈开；
    相邻片段保留 ``overlap`` 个字符的重叠，防止答案正好卡在边界上被切散。
    """
    max_chars = max_chars or settings.embedding_max_chars
    content = (text or "").strip()
    if not content:
        return []
    if len(content) <= max_chars:
        return [content]

    chunks: list[str] = []
    start = 0
    total = len(content)
    while start < total:
        end = min(start + max_chars, total)
        if end < total:
            window = content[start:end]
            cut = -1
            for mark in _BREAKS:
                idx = window.rfind(mark)
                if idx >= int(max_chars * 0.5):
                    cut = max(cut, idx)
            if cut > 0:
                end = start + cut + 1
        piece = content[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= total:
            break
        # 保证每次至少前进 1 个字符，避免 overlap ≥ 窗口时死循环
        start = max(start + 1, end - overlap)
    return chunks


# ---------------------------------------------------------------------------
# Qdrant
# ---------------------------------------------------------------------------


def _client() -> AsyncQdrantClient:
    return AsyncQdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key or None,
        timeout=30,
        # 本机 Qdrant 与 Python 客户端的小版本可能不一致，仅版本号告警，
        # 协议兼容，直接跳过检查避免日志噪音
        check_compatibility=False,
        # 与 app/ai/http_client.py 保持一致：不继承 HTTP_PROXY。
        # Qdrant 在本机/内网，走代理会绕一圈再失败；代理只认 OUTBOUND_PROXY。
        trust_env=False,
        proxy=settings.outbound_proxy.strip() or None,
    )


def get_client() -> AsyncQdrantClient:
    """对外暴露的客户端工厂（脚本/路由需要直接操作 collection 时用）。"""
    return _client()


async def ensure_collection(
    client: AsyncQdrantClient, *, recreate: bool = False
) -> str:
    """确保 collection 存在且维度与配置一致，返回 collection 名。"""
    name = settings.qdrant_collection
    exists = await client.collection_exists(name)
    if exists and recreate:
        await client.delete_collection(name)
        exists = False

    if not exists:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(
                size=settings.embedding_dim, distance=Distance.COSINE
            ),
        )
        logger.info(
            "已创建 Qdrant collection %s（%s 维 / COSINE）",
            name,
            settings.embedding_dim,
        )
        return name

    info = await client.get_collection(name)
    vectors = info.config.params.vectors
    size = getattr(vectors, "size", None)
    if size and int(size) != settings.embedding_dim:
        raise BadRequest(
            f"Qdrant collection {name} 是 {size} 维，"
            f"而配置 EMBEDDING_DIM={settings.embedding_dim}。"
            "请统一维度后重建（kb_builder.py --reset-vectors）"
        )
    return name


def _point_id(source: str, row_id: int, index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{source}:{row_id}:{index}"))


@dataclass
class Chunk:
    """一条待写入的向量点。"""

    point_id: str
    text: str
    payload: dict[str, Any] = field(default_factory=dict)


def build_law_chunks(article: LawArticle) -> list[Chunk]:
    """把一条法条切块（多数条文 1 块，超长条文 2~3 块）。"""
    pieces = chunk_text(article.content)
    total = len(pieces)
    out: list[Chunk] = []
    for i, piece in enumerate(pieces):
        out.append(
            Chunk(
                point_id=_point_id(KB_SOURCE_LAW, article.id, i),
                text=piece,
                payload={
                    "source": KB_SOURCE_LAW,
                    "article_id": article.id,
                    "law_name": article.law_name,
                    "chapter": article.chapter or "",
                    "article_no": article.article_no,
                    "effective_status": article.effective_status,
                    "chunk_index": i,
                    "chunk_count": total,
                    "content": piece,
                },
            )
        )
    return out


def build_firm_chunks(doc: KbDocument) -> list[Chunk]:
    """把一段律所自有知识切块。"""
    pieces = chunk_text(doc.content)
    total = len(pieces)
    out: list[Chunk] = []
    for i, piece in enumerate(pieces):
        out.append(
            Chunk(
                point_id=_point_id(KB_SOURCE_FIRM, doc.id, i),
                text=piece,
                payload={
                    "source": KB_SOURCE_FIRM,
                    "kb_id": doc.id,
                    "title": doc.title,
                    "category": doc.category,
                    "chunk_index": i,
                    "chunk_count": total,
                    "content": piece,
                },
            )
        )
    return out


async def _filter_new_chunks(
    client: AsyncQdrantClient, name: str, chunks: Sequence[Chunk]
) -> list[Chunk]:
    """挑出尚未写入 Qdrant、或正文已变化的块，用于断点续跑。

    点 ID 由 ``来源:主键:块序号`` 决定，与正文无关；因此这里比对 payload 中的
    ``content``，正文改过就重算，未改则跳过，避免重建索引时重复消耗算力。
    """
    if not chunks:
        return []
    ids = [c.point_id for c in chunks]
    try:
        found = await client.retrieve(
            collection_name=name,
            ids=ids,
            with_payload=["content"],
            with_vectors=False,
        )
    except Exception as exc:  # noqa: BLE001 - 探测失败时保守全量重算
        logger.warning("检查已存在向量失败，本批全部重算：%s", exc)
        return list(chunks)

    done = {str(point.id): (point.payload or {}).get("content") for point in found}
    return [c for c in chunks if done.get(c.point_id) != c.text]


async def _upsert(
    client: AsyncQdrantClient, name: str, chunks: Sequence[Chunk]
) -> None:
    """向量化并写入 Qdrant，按 256 点一批 upsert。"""
    if not chunks:
        return
    vectors = await embedding.embed_texts([c.text for c in chunks])
    points = [
        PointStruct(id=c.point_id, vector=vec, payload=c.payload)
        for c, vec in zip(chunks, vectors)
    ]
    for i in range(0, len(points), _UPSERT_BATCH):
        await client.upsert(
            collection_name=name,
            points=points[i : i + _UPSERT_BATCH],
            wait=True,
        )


async def index_law_articles(
    session: AsyncSession,
    articles: Sequence[LawArticle],
    *,
    client: AsyncQdrantClient | None = None,
    window: int = 128,
    resume: bool = True,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """批量向量化法条并回写 ``vector_id``，返回本次实际写入的向量点总数。

    :param resume: 为 ``True`` 时跳过 Qdrant 中已存在且正文一致的块，
        中断后重跑只补未完成的部分
    """
    own_client = client is None
    client = client or _client()
    total_points = 0
    done = 0
    failures = 0
    try:
        name = await ensure_collection(client)
        for start in range(0, len(articles), window):
            batch = list(articles[start : start + window])
            per_article: list[list[Chunk]] = []
            for art in batch:
                per_article.append(build_law_chunks(art))
            chunks = [c for group in per_article for c in group]
            todo = await _filter_new_chunks(client, name, chunks) if resume else chunks
            try:
                await _upsert(client, name, todo)
            except embedding.EmbeddingError as exc:
                # 单批失败不中断整轮：该批不回写 vector_id，重跑时会自动补
                failures += 1
                logger.warning(
                    "第 %d 批向量化失败（%d 条）已跳过，重跑可补齐：%s",
                    start // window + 1,
                    len(batch),
                    exc,
                )
                done += len(batch)
                if progress:
                    progress(done, len(articles))
                continue

            # 回写首块点 ID，方便从 DB 侧直接定位向量
            for art, group in zip(batch, per_article):
                if group:
                    art.vector_id = group[0].point_id
            # 每批提交：中断后已完成部分不回滚，重跑按 vector_id 续做
            await session.commit()

            total_points += len(todo)
            done += len(batch)
            if progress:
                progress(done, len(articles))
        if failures:
            logger.warning("本轮有 %d 批向量化失败，重跑 --index 可补齐", failures)
    finally:
        if own_client:
            await client.close()
    return total_points


async def index_kb_document(
    session: AsyncSession,
    doc: KbDocument,
    *,
    client: AsyncQdrantClient | None = None,
) -> int:
    """把一段律所知识写入向量库。"""
    if not doc.id:
        raise BadRequest("知识片段尚未保存，无法向量化")
    own_client = client is None
    client = client or _client()
    try:
        name = await ensure_collection(client)
        chunks = build_firm_chunks(doc)
        await _upsert(client, name, chunks)
        if chunks:
            doc.vector_id = chunks[0].point_id
            await session.commit()
        return len(chunks)
    finally:
        if own_client:
            await client.close()


async def index_pending_kb_documents(
    session: AsyncSession,
    *,
    client: AsyncQdrantClient | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> int:
    """把尚未向量化的律所知识批量写入，返回写入的点数。"""
    result = await session.execute(
        select(KbDocument).where(KbDocument.vector_id.is_(None)).order_by(KbDocument.id)
    )
    docs = list(result.scalars().all())
    if not docs:
        return 0

    own_client = client is None
    client = client or _client()
    total_points = 0
    try:
        name = await ensure_collection(client)
        for i, doc in enumerate(docs, start=1):
            chunks = build_firm_chunks(doc)
            await _upsert(client, name, chunks)
            if chunks:
                doc.vector_id = chunks[0].point_id
            total_points += len(chunks)
            if progress:
                progress(i, len(docs))
        await session.commit()
    finally:
        if own_client:
            await client.close()
    return total_points


async def delete_firm_vectors(
    doc_id: int, *, client: AsyncQdrantClient | None = None
) -> None:
    """删除某条律所知识在 Qdrant 中的全部点（按 kb_id 过滤）。"""
    own_client = client is None
    client = client or _client()
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            return
        await client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=Filter(
                must=[
                    FieldCondition(
                        key="source", match=MatchValue(value=KB_SOURCE_FIRM)
                    ),
                    FieldCondition(key="kb_id", match=MatchValue(value=doc_id)),
                ]
            ),
            wait=True,
        )
    finally:
        if own_client:
            await client.close()


async def delete_points(point_ids: Iterable[str]) -> None:
    """按点 ID 批量删除（重建索引时清理旧块用）。"""
    ids = [pid for pid in point_ids if pid]
    if not ids:
        return
    client = _client()
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            return
        await client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=PointIdsList(points=ids),
            wait=True,
        )
    finally:
        await client.close()


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


async def search_knowledge(
    query: str,
    *,
    top_k: int = 6,
    source: str | None = None,
    min_score: float | None = None,
) -> list[dict[str, Any]]:
    """语义检索 top-k，返回带 ``score`` 的 payload 列表。

    :param source: ``law`` 只查法条、``firm`` 只查律所知识、``None`` 全部
    :param min_score: 低于该余弦相似度的结果直接丢弃
    """
    text = (query or "").strip()
    if not text:
        raise BadRequest("检索内容不能为空")
    if not 1 <= top_k <= 50:
        raise BadRequest("top_k 需在 1~50 之间")

    client = _client()
    try:
        if not await client.collection_exists(settings.qdrant_collection):
            raise NotFound("知识库尚未初始化，请先执行 kb_builder.py --all")
        vector = await embedding.embed_query(text)
        query_filter = None
        if source in (KB_SOURCE_LAW, KB_SOURCE_FIRM):
            query_filter = Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            )
        result = await client.query_points(
            collection_name=settings.qdrant_collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
        )
    finally:
        await client.close()

    hits: list[dict[str, Any]] = []
    for point in result.points:
        payload = dict(point.payload or {})
        score = float(point.score)
        if min_score is not None and score < min_score:
            continue
        payload["score"] = round(score, 4)
        payload["point_id"] = str(point.id)
        hits.append(payload)
    return hits


# ---------------------------------------------------------------------------
# 统计
# ---------------------------------------------------------------------------


async def kb_stats(session: AsyncSession) -> dict[str, Any]:
    """知识库概览：条文数、知识片段数、向量点数、服务健康度。"""
    law_total = int(
        await session.scalar(select(func.count()).select_from(LawArticle)) or 0
    )
    firm_total = int(
        await session.scalar(select(func.count()).select_from(KbDocument)) or 0
    )
    by_law_rows = await session.execute(
        select(LawArticle.law_name, func.count()).group_by(LawArticle.law_name)
    )
    by_law = {name: int(count) for name, count in by_law_rows.all()}

    by_cat_rows = await session.execute(
        select(KbDocument.category, func.count()).group_by(KbDocument.category)
    )
    by_category = {cat: int(count) for cat, count in by_cat_rows.all()}

    vector_points = 0
    qdrant_ok = False
    qdrant_error: str | None = None
    client = _client()
    try:
        if await client.collection_exists(settings.qdrant_collection):
            info = await client.get_collection(settings.qdrant_collection)
            vector_points = int(info.points_count or 0)
            qdrant_ok = True
        else:
            qdrant_error = f"collection {settings.qdrant_collection} 不存在"
    except Exception as exc:  # noqa: BLE001 - 统计接口不应因向量库异常而整体失败
        qdrant_error = f"{exc.__class__.__name__}: {exc}"
    finally:
        await client.close()

    embed_health = await embedding.check_health()

    return {
        "law_total": law_total,
        "firm_total": firm_total,
        "law_by_name": by_law,
        "firm_by_category": by_category,
        "vector_points": vector_points,
        "collection": settings.qdrant_collection,
        "embedding_dim": settings.embedding_dim,
        "embedding_model": settings.embedding_model,
        "qdrant_ok": qdrant_ok,
        "qdrant_error": qdrant_error,
        "embedding_ok": bool(embed_health.get("ok")),
        "embedding_error": embed_health.get("error"),
    }


async def reindex_all_law(
    session: AsyncSession, *, progress: Callable[[int, int], None] | None = None
) -> int:
    """把库里全部法条重新向量化（换模型/改维度后用）。"""
    rows = await session.execute(select(LawArticle).order_by(LawArticle.id))
    articles = list(rows.scalars().all())
    if not articles:
        raise NotFound("law_article 表为空，请先执行 kb_builder.py --parse")
    return await index_law_articles(session, articles, progress=progress)


async def clear_law_vector_ids(session: AsyncSession) -> int:
    """清空法条的 vector_id，配合重建索引用。"""
    result = await session.execute(
        update(LawArticle)
        .values(vector_id=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return int(result.rowcount or 0)


async def clear_vector_ids(session: AsyncSession) -> tuple[int, int]:
    """清空法条与律所知识的 vector_id，返回 ``(法条数, 知识数)``。

    重建 collection 时必须**两类一起清**：只清法条的话，律所知识（FAQ/案例/
    手册）的 vector_id 仍指向已删除的 collection，而入库只挑 vector_id IS NULL
    的记录，于是这些知识会被永久跳过——表现为「换个向量模型后问律所收费
    标准，AI 说资料不足」，且日志里没有任何报错。
    """
    laws = await clear_law_vector_ids(session)
    result = await session.execute(
        update(KbDocument)
        .values(vector_id=None)
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return laws, int(result.rowcount or 0)
