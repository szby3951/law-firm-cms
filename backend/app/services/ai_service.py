"""RAG 问答服务（任务拆解 9.3.3 / 9.3.5）。

一次问答的完整链路：

.. code-block:: text

    校验会话 → 脱敏 → 检索 top-k → 拼提示词 → LLM 流式 → 逐段转发 + 分批落库
                                                        ↘ 解析 [n] → 存引用快照

三个设计决定，都是踩过坑之后的选择：

**1. 用户消息在流开始前落库，助手消息在第一段 token 到达时才建行。**
模型挂掉时不会留下一条空回答；同时也不需要在等待首 token 的那几秒里白占一个
数据库连接（连接池只有 10 个，流式请求可能挂十几秒）。

**2. 回答每 400 字提交一次。**
浏览器关页面、用户点"停止"都会让生成器被取消。只在结束时落库的话，这些半截
回答会全部丢失，而 9.9.3 要求"所有 AI 会话可审计"。分批提交后，断流也能留下
最后一段完整内容。

**3. 历史消息去掉旧的 ``[n]`` 再送模型。**
上一轮回答里的 [1] 指的是上一轮的法条；如果原样带进新提示词，模型会把它当成
本轮编号，答案里的引用就会指错条文。这个 bug 在测试里表现为"点了 [1] 弹出
不相关的法条"，很难从答案表面看出来。

SSE 事件约定（``event`` 名与 JSON 里的 ``type`` 一致，前端两种解析方式都能用）::

    meta    {session_id, model, provider, masked, top_k, disclaimer}
    stage   {stage: retrieving|generating, message}
    warning {detail}                       # 检索为空/失败，非致命
    refs    {items: [Reference...]}        # 编号 [1..n] 与提示词一致
    delta   {text}                         # 逐段正文
    done    {message_id, refs, used_refs, token_usage, elapsed_ms, disclaimer}
    error   {detail, retryable}

出现 ``error`` 即代表本次回答不完整，前端应标记"生成中断"而不是当成完整答案。

本模块只做**法律问答**：检索 ``law_kb``、按法条作答、结论标 ``[n]``。查本人
案件进度与费用是另一条链路（:mod:`app.services.business_chat_service`），两者
不共用提示词也不共用会话——原因见 ``app/ai/business_prompts.py`` 顶部说明。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import (
    business_prompts,
    case_prompts,
    contract_prompts,
    contract_text,
    doc_html,
    doc_prompts,
    profile_prompts,
    prompts,
    rag,
)
from app.ai.embedding import EmbeddingError
from app.ai.gateway import get_gateway
from app.ai.llm_clients.base import LLMError, Message
from app.ai.masking import mask_sensitive
from app.config import settings
from app.core.exceptions import AppError, BadRequest, Forbidden, NotFound
from app.database import SessionLocal
from app.models.ai import AiMessage, AiSession
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.document import Document
from app.models.user import User
from app.schemas.ai import (
    AiCaseSummaryIn,
    AiCaseSummaryOut,
    AiChatIn,
    AiContractReviewIn,
    AiDocArchiveIn,
    AiDocGenerateIn,
    AiMessageOut,
    AiProfileFields,
    AiProfileIn,
    AiProfileInputs,
    AiProfileOut,
    AiSessionCreate,
    AiSessionDetailOut,
    AiSessionOut,
    AiSessionUpdate,
)
from app.schemas.document import DOC_TYPE_LABELS, DocumentIn
from app.services import (
    audit_service,
    case_service,
    case_summary_service,
    client_profile_service,
    client_service,
    contract_service,
    dict_cache,
    doc_service,
)

logger = logging.getLogger(__name__)

__all__ = [
    "CaseSummaryPlan",
    "DocPlan",
    "ReviewPlan",
    "archive_document",
    "create_session",
    "delete_session",
    "estimate_tokens",
    "generate_client_profile",
    "get_client_profile",
    "get_latest_summary",
    "get_session",
    "list_sessions",
    "prepare_case_summary",
    "prepare_chat",
    "prepare_document",
    "prepare_review",
    "rename_session",
    "stream_case_summary",
    "stream_document",
    "stream_reply",
    "stream_review",
]

# 流式过程中每积累多少字符落一次库（约 1~2 秒的生成量）
_FLUSH_CHARS = 400

# 历史消息里需要剥掉的引用标记：[1] 【2】
_CITATION_RE = re.compile(r"[\[【]\s*\d{1,2}\s*[\]】]")
# 剥掉编号后常会留下「、、」这类连写分隔符，一并清掉
_LEFTOVER_RE = re.compile(r"[、,，;；]{2,}")


def _strip_citations(text: str) -> str:
    """去掉历史消息里的引用标记。

    上一轮的 [1] 指向上一轮的法条，带进新提示词会让模型把旧编号当成本轮编号，
    答案里的引用就会指错条文——而这种错误在答案表面完全看不出来。
    """
    return _LEFTOVER_RE.sub("", _CITATION_RE.sub("", text)).strip()


# ---------------------------------------------------------------------------
# 小工具
# ---------------------------------------------------------------------------


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数，用于 ``ai_message.token_usage`` 的用量统计。

    真实用量需要请求时带 ``stream_options: {include_usage: true}``，但多数
    OpenAI 兼容服务（包括部分自建网关）不支持，会让流式解析多出一种异常分支。
    这里按「中文 1 字 ≈ 0.75 token、西文 4 字符 ≈ 1 token」估算即可——
    该字段只用于展示与成本粗算，不参与计费。
    """
    if not text:
        return 0
    cjk = sum(1 for ch in text if "\u4e00" <= ch <= "\u9fff")
    return int(cjk * 0.75 + (len(text) - cjk) / 4) + 1


def sse(event: str, data: dict) -> str:
    """格式化一条 SSE 事件。``json.dumps`` 会把换行转义，不会破坏报文边界。"""
    payload = json.dumps({"type": event, **data}, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _make_title(question: str) -> str:
    """用首个问题生成会话标题（列表页展示用）。"""
    text = " ".join(question.split())
    return text if len(text) <= 28 else f"{text[:28]}…"


# ---------------------------------------------------------------------------
# 会话准备
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ChatPlan:
    """流式生成所需的全部上下文，在进入生成器前准备好。

    只携带值类型（ID、字符串、消息列表），不携带 ORM 对象：生成器运行在
    响应阶段，与请求级的数据库会话生命周期不一致，传对象极易触发
    ``MissingGreenlet`` 或"会话已关闭"。
    """

    session_id: int
    user_id: int
    role: str
    question: str
    masked_question: str
    history: list[Message] = field(default_factory=list)
    top_k: int = 6
    source: str | None = None
    mask_hits: dict[str, int] = field(default_factory=dict)
    is_new_session: bool = False


async def _load_history(db: AsyncSession, session_id: int) -> list[Message]:
    """取最近若干轮对话，脱敏、剥引用标记、按预算截断。"""
    rows = await db.execute(
        select(AiMessage)
        .where(
            AiMessage.session_id == session_id,
            AiMessage.role.in_(("user", "assistant")),
        )
        .order_by(AiMessage.id.desc())
        .limit(settings.ai_history_messages)
    )
    recent = list(reversed(rows.scalars().all()))

    history: list[Message] = []
    budget = settings.ai_history_max_chars * 2
    for msg in recent:
        text = _strip_citations(msg.content or "")
        if not text:
            continue
        # 历史里的敏感信息同样要打码，否则"历史 + 本轮"合起来仍可能带出明文
        text = mask_sensitive(text).text
        if len(text) > settings.ai_history_max_chars:
            text = f"{text[: settings.ai_history_max_chars]}…"
        history.append({"role": msg.role, "content": text})  # type: ignore[typeddict-item]
        budget -= len(text)

    # 预算超了就从头丢最旧的，保留最近的上下文
    while history and budget < 0:
        budget += len(history[0]["content"])
        history.pop(0)
    return history


async def prepare_chat(db: AsyncSession, user: User, payload: AiChatIn) -> ChatPlan:
    """校验/新建会话并落库用户消息，返回生成所需的计划。

    在进入流式响应之前调用，因此这里抛出的业务异常能被全局处理器转成正常的
    HTTP 状态码（404/403），不会出现"已经返回 200 再报错"的尴尬。
    """
    question = payload.question.strip()
    is_new = payload.session_id is None
    history: list[Message] = []

    if payload.session_id is not None:
        session = await db.get(AiSession, payload.session_id)
        if session is None:
            raise NotFound("会话不存在")
        if session.user_id != user.id:
            raise Forbidden("无权访问该会话")
        if session.type != "chat":
            # 「AI督办」的会话里全是金额与进度，续接到法律问答会把这些当成
            # 上下文继续推理；文书/案件会话同理。各入口只认自己的会话。
            raise NotFound("该会话不属于 AI 法律问答")
        history = await _load_history(db, session.id)
    else:
        session = AiSession(
            user_id=user.id, type="chat", title=_make_title(question)
        )
        db.add(session)
        await db.flush()

    db.add(AiMessage(session_id=session.id, role="user", content=question))
    session.updated_at = datetime.now()
    await db.commit()

    masked = mask_sensitive(question)
    if masked.masked:
        logger.info("问答前已脱敏：%s（session=%s）", masked.summary, session.id)

    return ChatPlan(
        session_id=session.id,
        user_id=user.id,
        role=user.role,
        question=question,
        masked_question=masked.text,
        history=history,
        top_k=payload.top_k or settings.rag_top_k,
        source=payload.source,
        mask_hits=masked.hits,
        is_new_session=is_new,
    )


# ---------------------------------------------------------------------------
# 流式回答
# ---------------------------------------------------------------------------


class _AssistantSink:
    """把流式增量写进 ``ai_message``，兼做断流留痕的缓冲。"""

    def __init__(self, session_id: int):
        self.session_id = session_id
        self.content = ""
        self._db: AsyncSession | None = None
        self._msg: AiMessage | None = None
        self._flushed = 0

    @property
    def started(self) -> bool:
        return self._msg is not None

    async def append(self, piece: str) -> None:
        """追加一段文本。首次调用时建行并提交，之后按字数批量提交。"""
        self.content += piece
        if self._msg is None:
            self._db = SessionLocal()
            self._msg = AiMessage(
                session_id=self.session_id, role="assistant", content=self.content
            )
            self._db.add(self._msg)
            await self._db.commit()
            self._flushed = len(self.content)
        elif len(self.content) - self._flushed >= _FLUSH_CHARS:
            self._msg.content = self.content
            await self._db.commit()  # type: ignore[union-attr]
            self._flushed = len(self.content)

    async def finalize(
        self,
        refs: list[rag.Reference],
        token_usage: int,
        *,
        note: str | None = None,
    ) -> int | None:
        """收尾：写全正文、引用快照与用量，并把会话的活跃时间往后推。

        :param note: 异常中断时追加的说明。已经推给前端的文本没法改，但落库的
            版本要能让人看出"这条回答是半截的"，否则回看历史会误当成完整答案。
        """
        if self._msg is None or self._db is None:
            return None
        self._msg.content = f"{self.content}\n\n{note}" if note else self.content
        self._msg.refs = [ref.to_dict() for ref in refs] or None
        self._msg.token_usage = token_usage
        await self._db.commit()
        await self._db.execute(
            update(AiSession)
            .where(AiSession.id == self.session_id)
            .values(updated_at=func.now())
        )
        await self._db.commit()
        return self._msg.id

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None


async def stream_reply(plan: ChatPlan) -> AsyncIterator[str]:
    """生成 SSE 事件流。**不要**抛异常到外层——响应头已经发出，只能走 error 事件。"""
    gateway = get_gateway()
    started = time.perf_counter()

    yield sse(
        "meta",
        {
            "session_id": plan.session_id,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "top_k": plan.top_k,
            "masked": bool(plan.mask_hits),
            "mask_hits": plan.mask_hits,
            "disclaimer": prompts.DISCLAIMER,
        },
    )

    # 未配置 Key 时直接失败：先跑一遍检索再报错会让用户白等两秒
    try:
        gateway.check_ready()
    except LLMError as exc:
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
        return

    # ---- 检索 ----
    yield sse("stage", {"stage": "retrieving", "message": "正在检索法律条文…"})
    refs: list[rag.Reference] = []
    retrieval_failed = False
    try:
        refs = await rag.retrieve(
            plan.masked_question, top_k=plan.top_k, source=plan.source
        )
    except (EmbeddingError, AppError) as exc:
        # 检索失败不让问答整体失败：模型仍可基于常识作答，但必须告诉用户
        # "这次没有法条依据"，否则用户会把无引用回答当成有依据的结论。
        retrieval_failed = True
        logger.warning("RAG 检索失败，降级为无资料回答：%s", exc)
        yield sse("warning", {"detail": "知识库暂时不可用，本次回答未引用法条"})
    if not refs and not retrieval_failed:
        yield sse("warning", {"detail": "未检索到相关法条，请谨慎参考回答"})

    yield sse("refs", {"items": [ref.to_dict() for ref in refs]})

    # ---- 生成 ----
    yield sse("stage", {"stage": "generating", "message": "正在生成回答…"})
    messages = prompts.build_chat_messages(
        plan.masked_question,
        refs,
        history=plan.history,
        role=plan.role,
    )
    prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))

    sink = _AssistantSink(plan.session_id)
    try:
        async for piece in gateway.chat(messages, fallback=None):
            await sink.append(piece)
            yield sse("delta", {"text": piece})

        content = sink.content
        if not content.strip():
            # 模型返回空串（部分网关在触发内容审核时会这样）：不落库、不留空回答
            yield sse("error", {"detail": "AI 未返回内容，请重试", "retryable": True})
            return

        token_usage = prompt_tokens + estimate_tokens(content)
        message_id = await sink.finalize(refs, token_usage)

        yield sse(
            "done",
            {
                "session_id": plan.session_id,
                "message_id": message_id,
                "refs": [ref.to_dict() for ref in refs],
                "used_refs": prompts.extract_used_refs(content, len(refs)),
                "token_usage": token_usage,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "disclaimer": prompts.DISCLAIMER,
            },
        )
        logger.info(
            "问答完成 | session=%s | 引用 %d 条 | 用量约 %d token | %.1fs",
            plan.session_id,
            len(refs),
            token_usage,
            time.perf_counter() - started,
        )
    except LLMError as exc:
        logger.warning("AI 回答失败（session=%s）：%s", plan.session_id, exc)
        if sink.started:
            await sink.finalize(
                refs,
                prompt_tokens + estimate_tokens(sink.content),
                note="（回答因 AI 服务异常中断，以上内容不完整）",
            )
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
    except asyncio.CancelledError:
        # 用户关页面/点停止：已提交的分批内容留在库里，不再尝试写收尾字段
        logger.info(
            "客户端断开（session=%s），已保留 %d 字",
            plan.session_id,
            len(sink.content),
        )
        raise
    except Exception:  # 兜底：流式响应已经开始，不能再让异常冒出去
        logger.exception("AI 回答异常（session=%s）", plan.session_id)
        if sink.started:
            await sink.finalize(
                refs,
                prompt_tokens + estimate_tokens(sink.content),
                note="（回答因系统异常中断，以上内容不完整）",
            )
        yield sse("error", {"detail": "AI 服务异常，请稍后重试", "retryable": True})
    finally:
        await sink.close()


# ---------------------------------------------------------------------------
# 文书生成（9.4.2 / 9.4.4）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class DocPlan:
    """一次文书生成所需的全部上下文。

    与 :class:`ChatPlan` 一样只带值类型。区别是这里多了 ``fields`` / ``missing``：
    前端要能直接看到"哪些字段取到了、哪些没取到"，否则律师拿到一份满是
    ``【待补充：受理法院】`` 的起诉状，只能自己逐项比对案件档案。
    """

    session_id: int
    user_id: int
    doc_type: str
    label: str
    title: str
    case_id: int | None
    messages: list[Message]
    fields: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)
    prompt_tokens: int = 0
    warnings: list[str] = field(default_factory=list)


def _document_instruction(
    label: str,
    *,
    case_no: str | None,
    case_title: str | None,
    facts: str,
    requirements: str | None,
) -> str:
    """生成一条可读的「用户指令」存进 ai_message，作为审计留痕。

    不直接存拼好的完整提示词：那份提示词包含系统角色设定与格式规范，
    几百行全部塞进消息表既难读、也会让历史会话接口返回一大坨内部内容。
    存"输入了什么"，配合固定的模板即可复现"当时送了什么"。
    """
    lines = [f"【AI 文书生成】{label}"]
    if case_no or case_title:
        lines.append(f"案件：{case_no or '-'} {case_title or ''}".strip())
    if requirements:
        lines.append(f"额外要求：{requirements}")
    lines.append("案件事实：")
    lines.append(facts)
    return "\n".join(lines)


async def prepare_document(
    db: AsyncSession, user: User, payload: AiDocGenerateIn
) -> DocPlan:
    """收集案件字段 → 组装提示词 → 建会话，返回生成计划（9.4.2）。

    这一步的异常都能被全局处理器转成正常 HTTP 状态码（403/404/400），
    因为它们发生在 SSE 响应开始之前。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权生成文书")

    spec = doc_prompts.get_spec(payload.doc_type)

    case = None
    client = None
    if payload.case_id is not None:
        case = await doc_service.get_editable_case(db, payload.case_id, user)
        client = await db.get(ClientProfile, case.client_id)

    # 复用文书模块的取值逻辑：客户档案 + 案件字段 + 律所信息 + 日期，
    # 保证 AI 生成与模板填充拿到的数据完全一致
    context = await doc_service.build_template_context(
        db, case=case, client=client, current=user
    )

    facts = (payload.facts or (case.description if case else "") or "").strip()
    if not facts:
        raise BadRequest(
            "该案件没有案情描述，请先补充案件事实再生成文书——"
            "没有事实的文书只会是一堆占位符"
        )
    context["案情描述"] = facts

    missing = [name for name in spec.fields if not context.get(name)]

    template_content: str | None = None
    warnings: list[str] = []
    if payload.template_id is not None:
        template = await doc_service.get_template(db, payload.template_id)
        template_content = template.content
        if template.doc_type != payload.doc_type:
            warnings.append(
                f"所选模板是「{dict_cache.label_of('doc_type', template.doc_type, DOC_TYPE_LABELS.get(template.doc_type, template.doc_type))}」，"
                "与本次文书类型不同，仅作格式参考"
            )

    # 案情描述单独作为【案件事实】段落呈现，不在字段清单里重复
    fields = {k: v for k, v in context.items() if k != "案情描述"}

    messages = doc_prompts.build_document_messages(
        doc_type=payload.doc_type,
        fields=fields,
        missing=missing,
        facts=facts,
        requirements=payload.requirements,
        template_content=template_content,
    )

    default_title = f"{context.get('客户姓名', '')}{spec.label}".strip()
    title = (payload.title or default_title or spec.label)[:255]

    session = AiSession(
        user_id=user.id,
        type="document",
        related_id=case.id if case else None,
        title=title,
    )
    db.add(session)
    await db.flush()

    db.add(
        AiMessage(
            session_id=session.id,
            role="user",
            content=_document_instruction(
                spec.label,
                case_no=case.case_no if case else None,
                case_title=case.title if case else None,
                facts=facts,
                requirements=payload.requirements,
            ),
        )
    )
    await db.commit()

    if missing:
        logger.info("文书生成缺字段：%s（session=%s）", "、".join(missing), session.id)

    return DocPlan(
        session_id=session.id,
        user_id=user.id,
        doc_type=payload.doc_type,
        label=spec.label,
        title=title,
        case_id=case.id if case else None,
        messages=messages,
        fields=fields,
        missing=missing,
        prompt_tokens=estimate_tokens("".join(m["content"] for m in messages)),
        warnings=warnings,
    )


async def stream_document(plan: DocPlan) -> AsyncIterator[str]:
    """流式生成文书初稿。

    事件：

    ::

        meta     {session_id, doc_type, doc_type_label, title, model, missing, disclaimer}
        context  {fields, missing, title}      # 实际带入的案件字段，前端可做"信息核对"面板
        warning  {detail}                      # 模板类型不符等非致命提示
        stage    {stage, message}
        delta    {text}
        done     {session_id, message_id, title, content, html, token_usage, elapsed_ms}
        error    {detail, retryable}
    """
    gateway = get_gateway()
    started = time.perf_counter()

    yield sse(
        "meta",
        {
            "session_id": plan.session_id,
            "doc_type": plan.doc_type,
            "doc_type_label": plan.label,
            "title": plan.title,
            "case_id": plan.case_id,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "missing": plan.missing,
            "disclaimer": doc_prompts.DISCLAIMER,
        },
    )

    try:
        gateway.check_ready()
    except LLMError as exc:
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
        return

    yield sse(
        "context",
        {"fields": plan.fields, "missing": plan.missing, "title": plan.title},
    )
    for note in plan.warnings:
        yield sse("warning", {"detail": note})

    yield sse("stage", {"stage": "generating", "message": "正在起草文书…"})

    sink = _AssistantSink(plan.session_id)
    try:
        async for piece in gateway.chat(plan.messages, fallback=None):
            await sink.append(piece)
            yield sse("delta", {"text": piece})

        content = sink.content
        if not content.strip():
            yield sse("error", {"detail": "AI 未返回内容，请重试", "retryable": True})
            return

        token_usage = plan.prompt_tokens + estimate_tokens(content)
        message_id = await sink.finalize([], token_usage)

        yield sse(
            "done",
            {
                "session_id": plan.session_id,
                "message_id": message_id,
                "title": plan.title,
                "doc_type": plan.doc_type,
                "doc_type_label": plan.label,
                "case_id": plan.case_id,
                # content 给编辑器做 Markdown 预览，html 可直接存 document.content，
                # 前端"一键归档"时不必自己再转一遍
                "content": content,
                "html": doc_html.to_html(content),
                "missing": plan.missing,
                "token_usage": token_usage,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "disclaimer": doc_prompts.DISCLAIMER,
            },
        )
        logger.info(
            "文书生成完成 | session=%s | %s | %d 字 | 缺字段 %d 项 | %.1fs",
            plan.session_id,
            plan.label,
            len(content),
            len(plan.missing),
            time.perf_counter() - started,
        )
    except LLMError as exc:
        logger.warning("文书生成失败（session=%s）：%s", plan.session_id, exc)
        if sink.started:
            await sink.finalize(
                [],
                plan.prompt_tokens + estimate_tokens(sink.content),
                note="（因 AI 服务异常中断，以上文书不完整）",
            )
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
    except asyncio.CancelledError:
        logger.info(
            "客户端断开（文书 session=%s），已保留 %d 字",
            plan.session_id,
            len(sink.content),
        )
        raise
    except Exception:  # 兜底：响应头已发出，只能走 error 事件
        logger.exception("文书生成异常（session=%s）", plan.session_id)
        if sink.started:
            await sink.finalize(
                [],
                plan.prompt_tokens + estimate_tokens(sink.content),
                note="（因系统异常中断，以上文书不完整）",
            )
        yield sse("error", {"detail": "AI 服务异常，请稍后重试", "retryable": True})
    finally:
        await sink.close()


async def archive_document(
    db: AsyncSession, user: User, payload: AiDocArchiveIn
) -> Document:
    """把文书正文归档为正式 ``document`` 记录（9.4.4）。

    归档而不是"生成即入库"，是因为模型初稿必须经律师修改：直接写入文书库
    会让「我的文书」里堆满需要删除的半成品。前端拿到 ``done`` 后让律师改，
    确认无误再调这里保存。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权归档文书")

    if payload.session_id is not None:
        session = await db.get(AiSession, payload.session_id)
        if session is None:
            raise NotFound("来源会话不存在")
        # 管理员可以归档他人代为生成的文书，普通律师只能归档自己的会话
        if session.user_id != user.id and user.role != "admin":
            raise Forbidden("无权引用该会话")

    # 归档即"在案件下建文书"，权限规则与手工新建完全一致
    if payload.case_id is not None:
        await doc_service.get_editable_case(db, payload.case_id, user)

    content = doc_html.to_html(payload.content)
    return await doc_service.create_document(
        db,
        DocumentIn(
            title=payload.title,
            doc_type=payload.doc_type,
            case_id=payload.case_id,
            content=content,
            status=payload.status,
            is_ai_generated=True,
            ai_session_id=payload.session_id,
        ),
        user,
    )


# ---------------------------------------------------------------------------
# 合同风险审查（9.5）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class ReviewPlan:
    """一次合同审查的全部上下文（都已备好，进入 SSE 后不再报 4xx）。"""

    contract_id: int
    user_id: int
    session_id: int
    meta: dict[str, Any]
    digest: contract_text.ContractDigest
    batches: list[list[contract_text.Clause]]
    focus: str | None = None
    save: bool = True
    prompt_tokens: int = 0


def _contract_meta(contract: Contract) -> dict[str, Any]:
    """合同台账字段 → 提示词与报告共用的元信息（金额、期限已经格式化）。"""
    type_label = contract_prompts.CONTRACT_TYPE_LABELS.get(
        contract.contract_type or "", contract.contract_type or "未标注"
    )
    amount_text = f"¥{contract.amount:,.2f}" if contract.amount else "未填写"
    period_text = ""
    if contract.start_date or contract.end_date:
        start = contract.start_date.isoformat() if contract.start_date else "—"
        end = contract.end_date.isoformat() if contract.end_date else "—"
        period_text = f"{start} 至 {end}"
    return {
        "id": contract.id,
        "name": contract.name,
        "type_label": type_label,
        "amount_text": amount_text,
        "period_text": period_text,
        "status_label": contract_prompts.CONTRACT_STATUS_LABELS.get(
            contract.status, contract.status
        ),
        "client_name": getattr(contract, "client_name", None),
        "case_title": getattr(contract, "case_title", None),
    }


def _review_instruction(
    meta: dict[str, Any],
    digest: contract_text.ContractDigest,
    batches: int,
    focus: str | None,
) -> str:
    """写进 ai_message 的「本次审查输入了什么」。

    不落合同全文：正文已在 ``contract.file_url`` 或律师的粘贴稿里，再把几万字
    复制进消息表只会让会话接口返回一整本书。这里记录足以复现审查范围的元信息。
    """
    lines = [f"【AI 合同风险审查】{meta['name']}"]
    lines.append(f"类型：{meta['type_label']}｜金额：{meta['amount_text']}")
    lines.append(
        f"文本：{digest.source}｜{digest.char_count} 字｜"
        f"{digest.clause_count} 条｜分 {batches} 批"
    )
    if digest.missing:
        lines.append(f"规则预检未命中：{'、'.join(digest.missing)}")
    if digest.placeholder_count:
        lines.append(f"空白/占位：{digest.placeholder_count} 处")
    if digest.truncated:
        lines.append("合同超长，仅审查前部条款")
    if focus:
        lines.append(f"关注点：{focus}")
    return "\n".join(lines)


async def prepare_review(
    db: AsyncSession, user: User, contract_id: int, payload: AiContractReviewIn
) -> ReviewPlan:
    """读取合同文本 → 切条款 → 分批 → 建会话（9.5.1）。

    这里的异常发生在 SSE 响应开始之前，能正常返回 403/404/400：权限不足、
    合同不存在、没上传文件、PDF 是扫描件、正文太短。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权审查合同")

    # 复用合同模块的行级权限：律师只能审自己承办案件或本人创建的合同
    contract = await contract_service.get_contract(db, contract_id, user)
    meta = _contract_meta(contract)

    if payload.text:
        text, source = payload.text, "paste"
    else:
        if not contract.file_url:
            raise BadRequest("该合同尚未上传合同文件，请先上传，或直接粘贴合同正文")
        rel_path = contract.file_url
        abs_path = (settings.upload_dir / rel_path).resolve()
        if not str(abs_path).startswith(str(settings.upload_dir.resolve())):
            raise BadRequest("合同文件路径异常")
        try:
            text, source = contract_text.extract_text(abs_path)
        except contract_text.ContractTextError as exc:
            raise BadRequest(str(exc)) from exc

    try:
        digest = contract_text.digest_contract(
            text, source=source, max_chars=settings.contract_review_max_chars
        )
    except contract_text.ContractTextError as exc:
        raise BadRequest(str(exc)) from exc

    batches, cut = contract_text.split_batches(
        digest.clauses,
        max_chars=settings.contract_review_batch_chars,
        max_batches=settings.contract_review_max_batches,
    )
    if cut:
        digest.truncated = True

    session = AiSession(
        user_id=user.id,
        type="contract",
        related_id=contract.id,
        title=f"{contract.name} 风险审查"[:255],
    )
    db.add(session)
    await db.flush()

    instruction = _review_instruction(meta, digest, len(batches), payload.focus)
    db.add(AiMessage(session_id=session.id, role="user", content=instruction))
    await db.commit()

    logger.info(
        "合同审查准备 | contract=%s | %d 字 / %d 条 / %d 批 | session=%s",
        contract.id,
        digest.char_count,
        digest.clause_count,
        len(batches),
        session.id,
    )
    return ReviewPlan(
        contract_id=contract.id,
        user_id=user.id,
        session_id=session.id,
        meta=meta,
        digest=digest,
        batches=batches,
        focus=payload.focus,
        save=payload.save,
        prompt_tokens=estimate_tokens(instruction),
    )


async def stream_review(plan: ReviewPlan) -> AsyncIterator[str]:
    """分批调用模型审查，合并结果后写回合同台账（9.5.2 ~ 9.5.4）。

    事件：

    ::

        meta      {contract_id, name, char_count, clause_count, batches, source,
                   truncated, model, provider, disclaimer}
        precheck  {elements, missing, placeholders, placeholder_count}
        warning   {detail}                    # 截断/某批失败，非致命
        stage     {stage: reviewing, batch, total, message}
        progress  {batch, total, found}       # 已累计发现的风险数
        done      {report, saved, reviewed_at, session_id, token_usage, elapsed_ms}
        error     {detail, retryable}

    某一批失败不终止整体：其余批次照常审，报告里注明「第 N 批失败」。
    只有**全部批次都失败**才发 ``error``，且不会写回台账——半份报告比没有报告
    更危险，律师会以为已经查过了。
    """
    gateway = get_gateway()
    started = time.perf_counter()
    total = len(plan.batches)

    yield sse(
        "meta",
        {
            "contract_id": plan.contract_id,
            "session_id": plan.session_id,
            "name": plan.meta.get("name"),
            "type_label": plan.meta.get("type_label"),
            "amount_text": plan.meta.get("amount_text"),
            "char_count": plan.digest.char_count,
            "clause_count": plan.digest.clause_count,
            "batches": total,
            "source": plan.digest.source,
            "truncated": plan.digest.truncated,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "disclaimer": contract_prompts.DISCLAIMER,
        },
    )

    try:
        gateway.check_ready()
    except LLMError as exc:
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
        return

    yield sse(
        "precheck",
        {
            "elements": plan.digest.elements,
            "missing": plan.digest.missing,
            "placeholders": plan.digest.placeholders,
            "placeholder_count": plan.digest.placeholder_count,
        },
    )
    if plan.digest.truncated:
        yield sse(
            "warning",
            {
                "detail": (
                    f"合同超过 {settings.contract_review_max_chars} 字"
                    f"或超过 {settings.contract_review_max_batches} 批，"
                    "仅审查了前面的条款，请对其余部分人工复核"
                )
            },
        )

    risks: list[dict] = []
    missing: list[str] = list(plan.digest.missing)
    notes: list[str] = []
    failures = 0
    token_usage = plan.prompt_tokens

    for index, batch in enumerate(plan.batches, 1):
        first, last = batch[0].no, batch[-1].no
        yield sse(
            "stage",
            {
                "stage": "reviewing",
                "batch": index,
                "total": total,
                "message": f"正在审查第 {index}/{total} 批（第 {first}~{last} 条）…",
            },
        )
        messages = contract_prompts.build_review_messages(
            digest=plan.digest,
            meta=plan.meta,
            clauses=batch,
            batch_index=index,
            batch_total=total,
            focus=plan.focus,
        )
        try:
            data = await gateway.generate_json(
                messages, max_tokens=settings.contract_review_max_tokens
            )
        except LLMError as exc:
            failures += 1
            logger.warning("合同审查第 %d/%d 批失败：%s", index, total, exc)
            notes.append(f"第 {index} 批审查失败：{exc.friendly}，该批条款未纳入报告")
            yield sse(
                "warning",
                {"detail": f"第 {index} 批审查失败（{exc.friendly}），该批条款未纳入报告"},
            )
            if failures == total:
                yield sse(
                    "error",
                    {"detail": exc.friendly, "retryable": exc.retryable},
                )
                return
            continue
        except Exception:
            failures += 1
            logger.exception("合同审查第 %d/%d 批异常", index, total)
            notes.append(f"第 {index} 批处理异常，该批条款未纳入报告")
            yield sse("warning", {"detail": f"第 {index} 批处理异常，该批条款未纳入报告"})
            if failures == total:
                yield sse(
                    "error", {"detail": "AI 服务异常，请稍后重试", "retryable": True}
                )
                return
            continue

        token_usage += estimate_tokens(json.dumps(data, ensure_ascii=False))
        batch_risks = contract_prompts.normalize_report(data, plan.digest)
        risks.extend(batch_risks)
        for item in contract_prompts.extract_missing(data):
            if item not in missing:
                missing.append(item)
        note = contract_prompts.extract_notes(data)
        if note:
            notes.append(f"第 {index} 批：{note}")

        yield sse(
            "progress",
            {
                "batch": index,
                "total": total,
                "found": len(risks),
                "clause_range": [first, last],
            },
        )

    # 规则预检与模型结论合并：缺管辖、空白未填这类判断规则更稳，两边都留
    merged = contract_prompts.merge_risks(
        risks, contract_prompts.precheck_risks(plan.digest)
    )
    reviewed_at = datetime.now()
    report = contract_prompts.assemble_report(
        meta=plan.meta,
        digest=plan.digest,
        risks=merged,
        missing=missing,
        notes=notes,
        model=settings.llm_model,
        provider=settings.llm_provider,
        reviewed_at=reviewed_at.isoformat(timespec="seconds"),
        batches=total,
        token_usage=token_usage,
    )

    saved = False
    if plan.save:
        try:
            saved = await _persist_review(plan, report)
        except Exception:
            logger.exception("合同审查报告写回失败（contract=%s）", plan.contract_id)
            yield sse(
                "warning",
                {"detail": "报告已生成，但保存到合同台账失败，请重试或联系管理员"},
            )

    yield sse(
        "done",
        {
            "contract_id": plan.contract_id,
            "session_id": plan.session_id,
            "report": report,
            "saved": saved,
            "reviewed_at": report["reviewed_at"],
            "token_usage": token_usage,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "disclaimer": contract_prompts.DISCLAIMER,
        },
    )
    logger.info(
        "合同审查完成 | contract=%s | %d 批 | 风险 %d 条（高 %d） | %d 字 | %.1fs",
        plan.contract_id,
        total,
        report["counts"]["total"],
        report["counts"]["high"],
        plan.digest.char_count,
        time.perf_counter() - started,
    )


async def _persist_review(plan: ReviewPlan, report: dict[str, Any]) -> bool:
    """把报告写回 ``contract.ai_review_report``，并留一条助手消息与审计日志。

    使用独立短会话而不是请求级 ``DbSession``：SSE 响应开始后 FastAPI 会清理
    ``yield`` 依赖，沿用请求会话会踩到"连接已关闭"（9.3 踩过一次）。
    """
    async with SessionLocal() as db:
        contract = await db.get(Contract, plan.contract_id)
        if contract is None:
            logger.warning("合同 %s 已被删除，报告未保存", plan.contract_id)
            return False

        contract.ai_review_report = report
        contract.ai_review_at = datetime.now()
        db.add(
            AiMessage(
                session_id=plan.session_id,
                role="assistant",
                content=contract_prompts.render_text(report),
                token_usage=report.get("token_usage"),
            )
        )
        await db.commit()

        await audit_service.write_log_safe(
            db,
            user_id=plan.user_id,
            action=audit_service.ACTION_AI_CHAT,
            target=f"contract:{plan.contract_id}",
            detail=(
                f"AI 合同审查「{plan.meta.get('name')}」，"
                f"识别风险 {report['counts']['total']} 处"
                f"（高 {report['counts']['high']}）"
            ),
        )
    return True


# ---------------------------------------------------------------------------
# 案件摘要（9.6）
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class CaseSummaryPlan:
    """一次案件摘要所需的全部上下文。

    ``bundle`` 里的材料已经裁剪完毕，进入 SSE 后不再查库、不再报 4xx：
    权限、案件不存在、材料读取失败都发生在 :func:`prepare_case_summary`。
    """

    case_id: int
    user_id: int
    session_id: int
    case_no: str
    case_title: str
    bundle: case_summary_service.CaseBundle
    messages: list[Message]
    focus: str | None = None
    prompt_tokens: int = 0


def _summary_instruction(
    bundle: case_summary_service.CaseBundle, focus: str | None
) -> str:
    """写进 ``ai_message`` 的「本次摘要读了什么」，作为可审计的输入清单。

    不落材料全文：几万字复制进消息表会让历史接口返回一整本书，而材料本身还在
    案卷里。记录纳入/未纳入的清单，配合固定提示词即可复现当时的摘要范围。
    """
    lines = [f"【AI 案件摘要】{bundle.case_no} {bundle.case_title}"]
    lines.append(
        f"纳入材料 {bundle.material_count} 份 / {bundle.total_chars} 字；"
        f"未纳入 {len(bundle.skipped)} 项"
    )
    for material in bundle.materials:
        flag = "（节选）" if material.truncated else ""
        lines.append(
            f"- {material.kind_label}《{material.title}》{material.chars} 字{flag}"
        )
    if bundle.skipped:
        lines.append("未纳入：")
        lines.extend(f"- {item}" for item in bundle.skipped)
    if focus:
        lines.append(f"关注点：{focus}")
    return "\n".join(lines)


def _summary_warnings(bundle: case_summary_service.CaseBundle) -> list[str]:
    """把材料裁剪情况翻译成前端可直接展示的一句话。"""
    if not bundle.materials:
        return ["没有读取到可用材料，本次摘要仅依据案件档案与时间线"]
    warnings: list[str] = []
    if bundle.truncated:
        warnings.append(
            f"案卷材料较多，本次纳入 {bundle.material_count} 份、"
            f"{bundle.total_chars:,} 字，超出部分已节选或未纳入，"
            "「材料缺口」一节请结合原始卷宗核对"
        )
    elif bundle.skipped:
        warnings.append(
            f"有 {len(bundle.skipped)} 份材料无法读取或未纳入，摘要可能未覆盖全部卷宗"
        )
    return warnings


async def prepare_case_summary(
    db: AsyncSession, user: User, case_id: int, payload: AiCaseSummaryIn
) -> CaseSummaryPlan:
    """聚合案件数据 → 拼提示词 → 建会话（9.6.1）。

    ``collect_case_bundle`` 内部复用案件模块的行级权限：非承办律师 403、
    案件不存在 404。这些异常发生在 SSE 开始之前，能正常转成 HTTP 状态码。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权生成案件摘要")

    bundle = await case_summary_service.collect_case_bundle(
        db, user, case_id, include_materials=payload.include_materials
    )
    messages = case_prompts.build_case_summary_messages(
        meta=bundle.meta,
        timeline=bundle.timeline,
        schedules=bundle.schedules,
        materials=[item.to_prompt_dict() for item in bundle.materials],
        skipped=bundle.skipped,
        focus=payload.focus,
    )

    session = AiSession(
        user_id=user.id,
        type="case",
        related_id=bundle.case_id,
        title=f"{bundle.case_no} 案件摘要"[:255],
    )
    db.add(session)
    await db.flush()

    instruction = _summary_instruction(bundle, payload.focus)
    db.add(AiMessage(session_id=session.id, role="user", content=instruction))
    await db.commit()

    logger.info(
        "案件摘要准备 | case=%s | 材料 %d 份 / %d 字 | session=%s",
        bundle.case_id,
        bundle.material_count,
        bundle.total_chars,
        session.id,
    )
    return CaseSummaryPlan(
        case_id=bundle.case_id,
        user_id=user.id,
        session_id=session.id,
        case_no=bundle.case_no,
        case_title=bundle.case_title,
        bundle=bundle,
        messages=messages,
        focus=payload.focus,
        prompt_tokens=estimate_tokens("".join(m["content"] for m in messages)),
    )


async def stream_case_summary(plan: CaseSummaryPlan) -> AsyncIterator[str]:
    """流式生成案件摘要（9.6.2）。

    事件：

    ::

        meta     {case_id, case_no, title, session_id, counts, truncated,
                  material_count, material_chars, model, provider, disclaimer}
        context  {case, timeline, schedules, materials, counts, skipped, focus}
        warning  {detail}                 # 材料超限/未读取到材料，非致命
        stage    {stage: generating, message}
        delta    {text}
        done     {session_id, message_id, case_id, content, html, materials,
                  token_usage, elapsed_ms, generated_at, disclaimer}
        error    {detail, retryable}
    """
    gateway = get_gateway()
    started = time.perf_counter()
    bundle = plan.bundle

    yield sse(
        "meta",
        {
            "case_id": plan.case_id,
            "case_no": plan.case_no,
            "title": plan.case_title,
            "session_id": plan.session_id,
            "counts": bundle.counts,
            "truncated": bundle.truncated,
            "material_count": bundle.material_count,
            "material_chars": bundle.total_chars,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "disclaimer": case_prompts.DISCLAIMER,
        },
    )

    try:
        gateway.check_ready()
    except LLMError as exc:
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
        return

    yield sse(
        "context",
        {
            "case": bundle.meta,
            "timeline": bundle.timeline,
            "schedules": bundle.schedules,
            "materials": [item.to_out() for item in bundle.materials],
            "counts": bundle.counts,
            "skipped": bundle.skipped,
            "focus": plan.focus,
        },
    )
    for note in _summary_warnings(bundle):
        yield sse("warning", {"detail": note})

    yield sse("stage", {"stage": "generating", "message": "正在归纳案件要点…"})

    sink = _AssistantSink(plan.session_id)
    try:
        async for piece in gateway.chat(
            plan.messages,
            max_tokens=settings.case_summary_max_tokens,
            fallback=None,
        ):
            await sink.append(piece)
            yield sse("delta", {"text": piece})

        content = sink.content
        if not content.strip():
            yield sse("error", {"detail": "AI 未返回内容，请重试", "retryable": True})
            return

        token_usage = plan.prompt_tokens + estimate_tokens(content)
        message_id = await sink.finalize([], token_usage)
        generated_at = datetime.now().isoformat(timespec="seconds")

        # 审计放在 done 之前：客户端收到 done 后可能立刻断开，
        # 生成器被取消时 done 之后的代码不保证执行
        await _audit_case_summary(plan, len(content))

        yield sse(
            "done",
            {
                "session_id": plan.session_id,
                "message_id": message_id,
                "case_id": plan.case_id,
                "case_no": plan.case_no,
                "title": plan.case_title,
                "content": content,
                # allow_html=False：模型输出不受信任，强制按 Markdown 转义后
                # 再给前端 v-html，避免夹带标签被执行
                "html": doc_html.to_html(content, allow_html=False),
                "materials": [item.to_out() for item in bundle.materials],
                "counts": bundle.counts,
                "truncated": bundle.truncated,
                "token_usage": token_usage,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "generated_at": generated_at,
                "disclaimer": case_prompts.DISCLAIMER,
            },
        )
        logger.info(
            "案件摘要完成 | case=%s | %d 字 | 材料 %d 份 | %.1fs",
            plan.case_id,
            len(content),
            bundle.material_count,
            time.perf_counter() - started,
        )
    except LLMError as exc:
        logger.warning("案件摘要失败（case=%s）：%s", plan.case_id, exc)
        if sink.started:
            await sink.finalize(
                [],
                plan.prompt_tokens + estimate_tokens(sink.content),
                note="（因 AI 服务异常中断，以上摘要不完整）",
            )
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
    except asyncio.CancelledError:
        logger.info(
            "客户端断开（案件摘要 case=%s），已保留 %d 字",
            plan.case_id,
            len(sink.content),
        )
        raise
    except Exception:  # 兜底：响应头已发出，只能走 error 事件
        logger.exception("案件摘要异常（case=%s）", plan.case_id)
        if sink.started:
            await sink.finalize(
                [],
                plan.prompt_tokens + estimate_tokens(sink.content),
                note="（因系统异常中断，以上摘要不完整）",
            )
        yield sse("error", {"detail": "AI 服务异常，请稍后重试", "retryable": True})
    finally:
        await sink.close()


async def _audit_case_summary(plan: CaseSummaryPlan, chars: int) -> None:
    """摘要完成后补一条审计日志。

    用独立短会话：SSE 响应开始后请求级 ``DbSession`` 已被 FastAPI 清理。
    审计失败只记日志，不影响已经推给前端的摘要。
    """
    try:
        async with SessionLocal() as db:
            await audit_service.write_log_safe(
                db,
                user_id=plan.user_id,
                action=audit_service.ACTION_AI_CHAT,
                target=f"case:{plan.case_id}",
                detail=(
                    f"AI 案件摘要 {plan.case_no}，{chars} 字，"
                    f"纳入材料 {plan.bundle.material_count} 份"
                ),
            )
    except Exception:  # pragma: no cover - 审计连接异常不应影响响应
        logger.exception("案件摘要审计日志写入失败（case=%s）", plan.case_id)


async def get_latest_summary(
    db: AsyncSession, user: User, case_id: int
) -> AiCaseSummaryOut:
    """读取当前律师为该案件生成的最近一份摘要（没有则 ``content=None``）。

    按 ``user_id`` 过滤是刻意的：摘要是律师的工作底稿，可能包含对己方不利的
    初步判断，管理员也不应看到他人的版本（与 9.3 会话隔离规则一致）。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权查看案件摘要")
    await case_service.get_case_detail(db, case_id, user)

    row = (
        await db.execute(
            select(AiMessage, AiSession)
            .join(AiSession, AiSession.id == AiMessage.session_id)
            .where(
                AiSession.user_id == user.id,
                AiSession.type == "case",
                AiSession.related_id == case_id,
                AiMessage.role == "assistant",
            )
            .order_by(AiMessage.id.desc())
            .limit(1)
        )
    ).first()
    if row is None:
        return AiCaseSummaryOut(case_id=case_id, disclaimer=case_prompts.DISCLAIMER)

    message, session = row
    return AiCaseSummaryOut(
        case_id=case_id,
        session_id=session.id,
        content=message.content,
        html=doc_html.to_html(message.content, allow_html=False),
        generated_at=message.created_at,
        disclaimer=case_prompts.DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# 客户画像（9.7）
# ---------------------------------------------------------------------------

_PROFILE_VERSION = 1


def _profile_inputs(
    bundle: client_profile_service.ClientBundle,
) -> AiProfileInputs:
    """把聚合适配成响应里的「本次读了什么」。"""
    return AiProfileInputs(
        counts=bundle.counts,
        stats=bundle.stats,
        skipped=bundle.skipped,
        masked={"hits": bundle.masked_hits, "summary": bundle.masked_summary},
    )


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_profile(
    raw: Any,
) -> tuple[AiProfileFields | None, AiProfileInputs | None, dict[str, Any]]:
    """解析库里的 ``ai_profile`` JSON。

    结构随版本变化或历史数据残缺时返回 ``profile=None`` 而不是 500——前端会显示
    「重新生成」，比整页报错更有用。
    """
    if not isinstance(raw, dict):
        return None, None, {}

    meta = raw.get("meta")
    meta = meta if isinstance(meta, dict) else {}

    try:
        fields = AiProfileFields.model_validate(raw.get("profile") or {})
    except ValidationError:
        logger.warning("客户画像字段结构不合法，已忽略：%s", raw.get("profile"))
        fields = None

    inputs = None
    if isinstance(raw.get("inputs"), dict):
        try:
            inputs = AiProfileInputs.model_validate(raw["inputs"])
        except ValidationError:
            inputs = None

    return fields, inputs, meta


async def generate_client_profile(
    db: AsyncSession, user: User, client_id: int, payload: AiProfileIn
) -> AiProfileOut:
    """聚合客户数据 → 脱敏 → LLM 输出 JSON → 写回 ``client_profile``（9.7.2~9.7.5）。

    与 9.3~9.6 的流式接口不同，这里是**一次性 JSON**：画像只有几百字，逐字推送
    没有意义，反而要额外处理「半截 JSON 不能入库」的问题。前端在等待期间显示
    loading，超时时间放宽到 120 秒。

    权限、客户不存在等错误在调用模型之前抛出，能正常返回 4xx；模型失败由全局
    处理器转 503；模型输出的结构问题转 400，并提示重新生成。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权生成客户画像")

    bundle = await client_profile_service.collect_client_bundle(db, user, client_id)
    client = await db.get(ClientProfile, client_id)
    if client is None:  # collect 已校验过，这里只是拿可写对象
        raise NotFound("客户不存在")

    messages = profile_prompts.build_profile_messages(
        meta=bundle.meta,
        follows=bundle.follows,
        cases=bundle.cases,
        contracts=bundle.contracts,
        billing=bundle.billing,
        messages=bundle.messages,
        skipped=bundle.skipped,
        focus=payload.focus,
    )

    gateway = get_gateway()
    gateway.check_ready()
    started = time.perf_counter()
    raw = await gateway.generate_json(
        messages,
        schema_hint=profile_prompts.PROFILE_SCHEMA_HINT,
        max_tokens=settings.client_profile_max_tokens,
    )

    try:
        profile = profile_prompts.normalize_profile(raw)
    except profile_prompts.ProfileFormatError as exc:
        # 模型答非所问（缺「客户类型」「核心诉求」）时不写库，保住上一版画像
        logger.warning("客户画像格式异常（client=%s）：%s", client_id, exc)
        raise BadRequest("AI 返回的客户画像结构不完整，请重新生成") from exc

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    # 截到秒：MySQL DATETIME 不存微秒，不截断的话本次响应与 GET 回填的时间戳
    # 会差 6 位小数，前端「刷新后时间变了」的假象就是这么来的
    generated_at = datetime.now().replace(microsecond=0)
    inputs = _profile_inputs(bundle)

    client.ai_profile = {
        "version": _PROFILE_VERSION,
        "profile": profile,
        "inputs": inputs.model_dump(),
        "meta": {
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "elapsed_ms": elapsed_ms,
            "generated_by": user.id,
            "generated_at": generated_at.isoformat(timespec="seconds"),
        },
    }
    client.ai_profile_at = generated_at
    await db.commit()

    # 审计只记规模与脱敏命中，不写客户姓名/电话：日志的读者未必有权看客户资料
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_AI_CHAT,
        target=f"client:{client_id}",
        detail=(
            f"生成 AI 客户画像（客户 #{client_id}，"
            f"纳入 {bundle.counts.get('included', 0)} 条记录，"
            f"{len(profile['tags'])} 个标签，脱敏 {bundle.masked_summary or '无'}）"
        ),
    )

    logger.info(
        "客户画像完成 | client=%s | 标签 %d | 风险 %d | 输入 %d 字 | %.1fs",
        client_id,
        len(profile["tags"]),
        len(profile["risks"]),
        bundle.total_chars,
        elapsed_ms / 1000,
    )

    return AiProfileOut(
        client_id=client_id,
        profile=AiProfileFields.model_validate(profile),
        inputs=inputs,
        ai_profile_at=generated_at,
        generated_by=user.id,
        model=settings.llm_model,
        elapsed_ms=elapsed_ms,
        disclaimer=profile_prompts.DISCLAIMER,
    )


async def get_client_profile(db: AsyncSession, user: User, client_id: int) -> AiProfileOut:
    """读取已存档的客户画像（没有则 ``profile=None``）。

    画像按客户存档而不是按律师：负责律师换人时，接手的律师应当直接看到上一份
    判断，而不是从零开始。读取仍受行级权限约束（`client_service.get_client`）。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权查看客户画像")

    client = await client_service.get_client(db, client_id, user)
    fields, inputs, meta = _parse_profile(client.ai_profile)

    return AiProfileOut(
        client_id=client.id,
        profile=fields,
        inputs=inputs,
        ai_profile_at=client.ai_profile_at,
        generated_by=_as_int(meta.get("generated_by")),
        model=meta.get("model") if isinstance(meta.get("model"), str) else None,
        elapsed_ms=_as_int(meta.get("elapsed_ms")),
        disclaimer=profile_prompts.DISCLAIMER if fields else "",
    )


# ---------------------------------------------------------------------------
# 会话管理（9.3.5）
# ---------------------------------------------------------------------------


def _to_out(session: AiSession, count: int) -> AiSessionOut:
    out = AiSessionOut.model_validate(session)
    out.message_count = count
    return out


async def list_sessions(
    db: AsyncSession,
    user: User,
    *,
    page: int = 1,
    page_size: int = 20,
    session_type: str | None = None,
) -> tuple[int, list[AiSessionOut]]:
    """当前用户的会话列表，按最后活跃时间倒序。

    :param session_type: 只看某一类（``chat`` 法律问答 / ``business`` AI督办）。
        不传则返回全部——两个入口的侧栏各传各的，否则用户会在法律问答的历史里
        看到一堆「我还差多少钱」的业务会话。
    """
    where = [AiSession.user_id == user.id]
    if session_type:
        where.append(AiSession.type == session_type)

    total = int(
        await db.scalar(select(func.count()).select_from(AiSession).where(*where))
        or 0
    )
    if total == 0:
        return 0, []

    counter = (
        select(AiMessage.session_id.label("sid"), func.count().label("cnt"))
        .group_by(AiMessage.session_id)
        .subquery()
    )
    rows = await db.execute(
        select(AiSession, func.coalesce(counter.c.cnt, 0))
        .outerjoin(counter, counter.c.sid == AiSession.id)
        .where(*where)
        .order_by(AiSession.updated_at.desc(), AiSession.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    return total, [_to_out(session, int(cnt)) for session, cnt in rows.all()]


async def _get_owned(db: AsyncSession, user: User, session_id: int) -> AiSession:
    session = await db.get(AiSession, session_id)
    if session is None:
        raise NotFound("会话不存在")
    if session.user_id != user.id:
        # 用 403 而不是 404：会话确实存在，只是不属于你。管理员也不越权查看，
        # 避免"管理员能翻所有律师的咨询记录"这种越界。
        raise Forbidden("无权访问该会话")
    return session


async def get_session(
    db: AsyncSession,
    user: User,
    session_id: int,
    *,
    limit: int = 200,
    session_type: str | None = None,
) -> AiSessionDetailOut:
    """会话详情：按时间正序返回消息，附带免责声明。

    :param session_type: 传 ``chat`` / ``business`` 时校验会话归属，用于两个入口
        互相隔离——督办会话里全是金额与进度，出现在法律问答的历史里会被当成
        法律事实读。不匹配按 404 处理，而不是 403：告诉调用方"这个 id 存在但
        不属于你正在用的入口"，等于泄露了他人会话存在性。
    """
    session = await _get_owned(db, user, session_id)
    if session_type and session.type != session_type:
        raise NotFound("会话不存在")
    rows = await db.execute(
        select(AiMessage)
        .where(AiMessage.session_id == session_id)
        .order_by(AiMessage.id)
        .limit(limit)
    )
    messages = list(rows.scalars().all())
    out = AiSessionDetailOut.model_validate(session)
    out.message_count = len(messages)
    out.messages = [AiMessageOut.model_validate(msg) for msg in messages]
    # 业务会话查的是台账，套用"不构成法律意见"会让用户以为自己在咨询
    out.disclaimer = (
        business_prompts.BUSINESS_DISCLAIMER
        if session.type == "business"
        else prompts.DISCLAIMER
    )
    return out


async def create_session(
    db: AsyncSession, user: User, payload: AiSessionCreate
) -> AiSessionOut:
    """新建空会话。``/chat`` 不传 session_id 时也会自动建，此接口供前端先开壳。"""
    session = AiSession(
        user_id=user.id,
        type="chat",
        title=(payload.title or "新会话").strip() or "新会话",
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return _to_out(session, 0)


async def rename_session(
    db: AsyncSession, user: User, session_id: int, payload: AiSessionUpdate
) -> AiSessionOut:
    session = await _get_owned(db, user, session_id)
    session.title = payload.title
    await db.commit()
    # updated_at 由 onupdate 生成，提交后该属性处于过期状态；异步下懒加载会抛
    # MissingGreenlet，必须显式 refresh 再序列化
    await db.refresh(session)
    count = int(
        await db.scalar(
            select(func.count()).select_from(AiMessage).where(
                AiMessage.session_id == session_id
            )
        )
        or 0
    )
    return _to_out(session, count)


async def delete_session(db: AsyncSession, user: User, session_id: int) -> None:
    """删除会话。消息由 ``ai_message`` 的外键 ``ON DELETE CASCADE`` 一并清理。"""
    session = await _get_owned(db, user, session_id)
    await db.delete(session)
    await db.commit()
