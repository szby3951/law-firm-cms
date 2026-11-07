"""RAG 检索器（任务拆解 9.3.1）。

一条链路四个动作：

1. **向量化** 问题 → :func:`app.ai.embedding.embed_query`
2. **检索** Qdrant top-k，按相似度取回法条与律所知识
3. **归并** 同一条文被切成多块时合并为一条引用（否则 top-6 可能全被同一条
   长条文的分块占满，正确答案反而挤不进来）
4. **拼装** 成带编号的上下文，供 :mod:`app.ai.prompts` 塞进提示词

编号 ``[1] [2] ...`` 在这里一次性确定并随回答落库，前端点开 [n] 就能拿到
对应原文——这是「可溯源」的关键：编号必须与送给模型的那份上下文完全一致，
所以不要在别处重新排序。

检索失败（TEI 挂了、collection 未建）不抛给接口层，由调用方降级为纯模型回答，
主流程不中断（9.9.4）。
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from typing import Any

from app.config import settings
from app.services import kb_service

logger = logging.getLogger(__name__)

__all__ = ["Reference", "format_context", "retrieve"]


@dataclass(slots=True)
class Reference:
    """一条引用（一篇法条或一段律所知识）。"""

    index: int
    source: str  # law / firm
    content: str
    score: float
    # 法条
    article_id: int | None = None
    law_name: str | None = None
    chapter: str | None = None
    article_no: str | None = None
    effective_status: str | None = None
    # 律所知识
    kb_id: int | None = None
    title: str | None = None
    category: str | None = None
    # 溯源
    point_id: str | None = None

    @property
    def label(self) -> str:
        """用于提示词与前端展示的标题，如「《民法典》第五百八十五条」。"""
        if self.source == "law":
            name = self.law_name or "法律"
            return f"《{name}》{self.article_no or ''}".strip()
        return f"律所知识《{self.title or '未命名'}》"

    @property
    def meta_line(self) -> str:
        """标签行里括号中的补充信息（章节 / 分类 + 效力状态）。"""
        parts: list[str] = []
        if self.source == "law":
            if self.chapter:
                parts.append(self.chapter)
            if self.effective_status:
                parts.append(self.effective_status)
        else:
            parts.append(kb_service.CATEGORY_LABELS.get(self.category or "", "知识"))
        return " · ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """落库与 SSE 输出用。字段名对前端友好，不暴露内部结构。"""
        return {
            "index": self.index,
            "source": self.source,
            "label": self.label,
            "content": self.content,
            "score": self.score,
            "article_id": self.article_id,
            "law_name": self.law_name,
            "chapter": self.chapter,
            "article_no": self.article_no,
            "effective_status": self.effective_status,
            "kb_id": self.kb_id,
            "title": self.title,
            "category": self.category,
            "point_id": self.point_id,
        }

    def as_dict(self) -> dict[str, Any]:
        """调试用：含全部字段。"""
        return asdict(self)


def _merge_chunks(hits: list[dict[str, Any]]) -> str:
    """把同一条文/知识的多个分块拼回正文，并去掉切块时的重叠部分。

    ``chunk_text`` 在相邻块之间保留了 60 字重叠（防止答案卡在边界上被切散），
    直接首尾相接会出现重复段落，因此逐块比对「已有文本的结尾」与「新块的开头」，
    重叠部分只保留一份。
    """
    ordered = sorted(hits, key=lambda h: int(h.get("chunk_index") or 0))
    merged = ""
    for hit in ordered:
        piece = (hit.get("content") or "").strip()
        if not piece:
            continue
        if not merged:
            merged = piece
            continue
        if piece in merged:
            continue
        # 找最大重叠：从 80 字往下试，取第一个能把两段接上的长度
        overlap = 0
        for size in range(min(80, len(merged), len(piece)), 7, -1):
            if merged.endswith(piece[:size]):
                overlap = size
                break
        merged = f"{merged}{piece[overlap:]}"
    return merged


async def retrieve(
    question: str,
    *,
    top_k: int | None = None,
    source: str | None = None,
    min_score: float | None = None,
) -> list[Reference]:
    """检索并整理成编号引用列表。

    :param question: 已脱敏的问题文本
    :param top_k: 最终引用条数，缺省 ``settings.rag_top_k``（设计文档 5~8）
    :param source: 只查法条 / 只查律所知识，``None`` 表示全部
    :param min_score: 相似度下限，缺省 ``settings.rag_min_score``；
        传 0 关闭过滤（调试检索效果时用）
    """
    text = (question or "").strip()
    if not text:
        return []

    limit = top_k or settings.rag_top_k
    threshold = settings.rag_min_score if min_score is None else min_score

    # 多要一些候选：分块会被归并，取 limit 条原始命中可能只剩 3~4 条引用
    candidates = await kb_service.search_knowledge(
        text,
        top_k=max(limit * 3, limit + 4),
        source=source,
        min_score=threshold if threshold and threshold > 0 else None,
    )
    if not candidates:
        logger.info("RAG 未检索到相关资料（query=%s）", text[:40])
        return []

    # 同一条文按 (source, 主键) 归并
    grouped: dict[tuple[str, int | None], list[dict[str, Any]]] = {}
    for hit in candidates:
        key = (
            str(hit.get("source") or ""),
            hit.get("article_id") if hit.get("source") == "law" else hit.get("kb_id"),
        )
        grouped.setdefault(key, []).append(hit)

    ranked: list[tuple[float, dict[str, Any], list[dict[str, Any]]]] = []
    for group in grouped.values():
        best = max(group, key=lambda h: float(h.get("score") or 0))
        ranked.append((float(best.get("score") or 0), best, group))
    ranked.sort(key=lambda item: item[0], reverse=True)

    refs: list[Reference] = []
    used_chars = 0
    for score, best, group in ranked:
        if len(refs) >= limit:
            break
        content = _merge_chunks(group)[: settings.rag_ref_max_chars]
        if not content:
            continue
        if used_chars + len(content) > settings.rag_max_context_chars and refs:
            # 上下文已满：剩下的低分引用直接丢弃，而不是截断成半句话
            break
        used_chars += len(content)
        refs.append(
            Reference(
                index=len(refs) + 1,
                source=str(best.get("source") or ""),
                content=content,
                score=round(score, 4),
                article_id=best.get("article_id"),
                law_name=best.get("law_name"),
                chapter=best.get("chapter") or None,
                article_no=best.get("article_no"),
                effective_status=best.get("effective_status"),
                kb_id=best.get("kb_id"),
                title=best.get("title"),
                category=best.get("category"),
                point_id=best.get("point_id"),
            )
        )
    return refs


def format_context(refs: list[Reference]) -> str:
    """拼装成提示词里的【参考资料】段落。

    每条都带编号与出处，模型标注 ``[n]`` 时才能对上号；没有检索结果时给一句
    明确的占位说明，避免模型把"空上下文"当成"没有限制"而自由发挥。
    """
    if not refs:
        return "（本次未检索到相关资料）"

    blocks: list[str] = []
    for ref in refs:
        meta = ref.meta_line
        header = f"[{ref.index}] {ref.label}" + (f"（{meta}）" if meta else "")
        blocks.append(f"{header}\n{ref.content}")
    return "\n\n".join(blocks)
