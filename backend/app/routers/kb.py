"""知识库管理路由（模块 9.1.5）。

挂在 ``/api/admin/kb`` 下，**仅管理员**可访问：

- ``GET  /stats``            知识库概览（条数 / 向量数 / 服务健康度）
- ``GET  /law-articles``     法条清单（按法律、关键词筛选，验证入库结果）
- ``GET  /documents``        律所知识列表
- ``POST /documents``        上传律所知识（FAQ / 案件摘要 / 办案手册），即时向量化
- ``PATCH /documents/{id}``  修改，正文变更会重建向量
- ``DELETE /documents/{id}`` 删除，同时清理向量点
- ``POST /search``           语义检索（9.1.4 验收：查询相似条文返回 top-k）

9.3 的 RAG 问答会复用 ``kb_service.search_knowledge``，届时再开面向律师的检索入口。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import func, select

from app.ai.embedding import EmbeddingError
from app.core.exceptions import BadRequest, NotFound
from app.dependencies import DbSession, client_ip, require_role
from app.models.kb_document import KbDocument
from app.models.law_article import LawArticle
from app.models.user import User
from app.schemas.kb import (
    KbDocumentCreate,
    KbDocumentListOut,
    KbDocumentOut,
    KbDocumentUpdate,
    KbHit,
    KbSearchIn,
    KbSearchOut,
    KbStatsOut,
    LawArticleOut,
)
from app.services import audit_service, kb_service

router = APIRouter()

logger = logging.getLogger(__name__)

AdminUser = Annotated[User, Depends(require_role("admin"))]


# ---------------------------------------------------------------------------
# 概览
# ---------------------------------------------------------------------------


@router.get("/stats", response_model=KbStatsOut, summary="知识库概览")
async def kb_overview(db: DbSession, user: AdminUser) -> KbStatsOut:
    """条文数、律所知识数、向量点数，以及 Qdrant / Embedding 的连通性。"""
    return KbStatsOut(**await kb_service.kb_stats(db))


# ---------------------------------------------------------------------------
# 法条
# ---------------------------------------------------------------------------


@router.get(
    "/law-articles",
    response_model=list[LawArticleOut],
    summary="法条清单（分页）",
)
async def list_law_articles(
    db: DbSession,
    user: AdminUser,
    law_name: str | None = Query(default=None, description="法律名称，支持模糊"),
    keyword: str | None = Query(default=None, description="条号或正文关键词"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> list[LawArticleOut]:
    """查看入库的法条，便于核对导入结果。"""
    stmt = select(LawArticle)
    if law_name:
        stmt = stmt.where(LawArticle.law_name.contains(law_name))
    if keyword:
        stmt = stmt.where(
            LawArticle.article_no.contains(keyword)
            | LawArticle.content.contains(keyword)
        )
    rows = await db.execute(
        stmt.order_by(LawArticle.id).offset((page - 1) * page_size).limit(page_size)
    )
    return [LawArticleOut.model_validate(row) for row in rows.scalars().all()]


@router.get("/law-articles/count", summary="法条数量（按法律分组）")
async def count_law_articles(db: DbSession, user: AdminUser) -> dict[str, int]:
    rows = await db.execute(
        select(LawArticle.law_name, func.count()).group_by(LawArticle.law_name)
    )
    return {name: int(count) for name, count in rows.all()}


# ---------------------------------------------------------------------------
# 律所知识（FAQ / 案件摘要 / 手册）
# ---------------------------------------------------------------------------


@router.get("/documents", response_model=KbDocumentListOut, summary="律所知识列表")
async def list_kb_documents(
    db: DbSession,
    user: AdminUser,
    category: str | None = Query(default=None, description="faq/case_summary/manual"),
    keyword: str | None = Query(default=None, description="标题关键词"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> KbDocumentListOut:
    stmt = select(KbDocument)
    if category:
        stmt = stmt.where(KbDocument.category == category)
    if keyword:
        stmt = stmt.where(KbDocument.title.contains(keyword))
    total = int(await db.scalar(select(func.count()).select_from(stmt.subquery())) or 0)
    rows = await db.execute(
        stmt.order_by(KbDocument.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return KbDocumentListOut(
        total=total,
        items=[KbDocumentOut.model_validate(row) for row in rows.scalars().all()],
    )


@router.post(
    "/documents",
    response_model=KbDocumentOut,
    status_code=201,
    summary="上传律所知识",
)
async def create_kb_document(
    db: DbSession,
    user: AdminUser,
    payload: KbDocumentCreate,
    request: Request,
) -> KbDocumentOut:
    """写入知识片段并立即向量化，随后即可被检索。"""
    doc = KbDocument(
        title=payload.title,
        category=payload.category,
        content=payload.content,
        created_by=user.id,
    )
    db.add(doc)
    await db.flush()

    try:
        await kb_service.index_kb_document(db, doc)
    except EmbeddingError as exc:
        # 入库成功但向量化失败：保留数据，提示稍后重建，不整单回滚
        await db.commit()
        raise BadRequest(f"知识已保存，但向量化失败：{exc}") from exc

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"kb_document:{doc.id}",
        detail=f"上传律所知识「{doc.title}」",
        ip=client_ip(request),
    )
    # created_at 由数据库默认值生成，提交后处于过期状态，需显式刷新再序列化
    await db.refresh(doc)
    return KbDocumentOut.model_validate(doc)


@router.patch(
    "/documents/{doc_id}", response_model=KbDocumentOut, summary="修改律所知识"
)
async def update_kb_document(
    db: DbSession,
    user: AdminUser,
    doc_id: int,
    payload: KbDocumentUpdate,
    request: Request,
) -> KbDocumentOut:
    doc = await db.get(KbDocument, doc_id)
    if doc is None:
        raise NotFound("知识片段不存在")

    changed_vector = False
    if payload.title is not None:
        doc.title = payload.title
    if payload.category is not None:
        doc.category = payload.category
    if payload.content is not None and payload.content != doc.content:
        doc.content = payload.content
        changed_vector = True

    await db.flush()
    if changed_vector:
        doc.vector_id = None
        try:
            await kb_service.index_kb_document(db, doc)
        except EmbeddingError as exc:
            await db.commit()
            raise BadRequest(f"修改已保存，但向量重建失败：{exc}") from exc
    await db.commit()

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"kb_document:{doc.id}",
        detail=f"修改律所知识「{doc.title}」",
        ip=client_ip(request),
    )
    await db.refresh(doc)
    return KbDocumentOut.model_validate(doc)


@router.delete("/documents/{doc_id}", status_code=204, summary="删除律所知识")
async def delete_kb_document(
    db: DbSession,
    user: AdminUser,
    doc_id: int,
    request: Request,
) -> None:
    doc = await db.get(KbDocument, doc_id)
    if doc is None:
        raise NotFound("知识片段不存在")
    title = doc.title
    await db.delete(doc)
    await db.commit()

    # 向量删除失败不影响业务数据，仅记录日志
    try:
        await kb_service.delete_firm_vectors(doc_id)
    except Exception as exc:  # noqa: BLE001 - 向量库异常不应阻断删除
        logger.warning("删除律所知识 %s 的向量失败：%s", doc_id, exc)

    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_DELETE,
        target=f"kb_document:{doc_id}",
        detail=f"删除律所知识「{title}」",
        ip=client_ip(request),
    )


# ---------------------------------------------------------------------------
# 检索（9.1.4 验收入口）
# ---------------------------------------------------------------------------


@router.post("/search", response_model=KbSearchOut, summary="语义检索 top-k")
async def search(db: DbSession, user: AdminUser, payload: KbSearchIn) -> KbSearchOut:
    """按语义相似度检索法条与律所知识，用于验证向量化效果。"""
    hits = await kb_service.search_knowledge(
        payload.query,
        top_k=payload.top_k,
        source=payload.source,
        min_score=payload.min_score,
    )
    return KbSearchOut(
        query=payload.query,
        count=len(hits),
        items=[KbHit(**hit) for hit in hits],
    )
