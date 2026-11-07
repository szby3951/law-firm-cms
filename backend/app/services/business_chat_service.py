"""「AI督办」服务：读台账回答本人业务问题（9.11）。

与 :mod:`app.services.ai_service` 并列，不是它的分支。两条链路的差别：

.. code-block:: text

    AI 法律问答  问题 → 脱敏 → 向量检索 law_kb → 法条 + 问题 → 流式 → 标 [n]
    AI督办     问题 → 脱敏 → 读业务快照   → 台账 + 问题 → 流式 → 抄数字

业务侧**没有检索**，因此没有 ``refs`` / ``warning`` 事件；也**不做意图判定**——
用户点进这个模块，意图已经确定，不需要猜。

会话写入复用 :class:`app.services.ai_service._AssistantSink`：断流留痕、分批提交、
首次出字才建行这些行为两边一致，没必要维护两份。区别只在 ``ai_session.type``，
列表页据此把两类会话分开显示。

SSE 事件::

    meta    {session_id, model, provider, masked, mask_hits, disclaimer}
    context {scope, as_of, items, counts, truncated, chars}
    stage   {stage: reading|generating, message}
    delta   {text}
    done    {message_id, token_usage, elapsed_ms, disclaimer}
    error   {detail, retryable}
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import business_prompts
from app.ai.gateway import get_gateway
from app.ai.llm_clients.base import LLMError, Message
from app.ai.masking import mask_sensitive
from app.config import settings
from app.core.exceptions import Forbidden, NotFound
from app.models.ai import AiMessage, AiSession
from app.models.user import User
from app.schemas.ai import BusinessChatIn
from app.services import personal_context_service
from app.services.ai_service import (
    _AssistantSink,
    _load_history,
    _make_title,
    estimate_tokens,
    sse,
)

__all__ = [
    "BusinessPlan",
    "prepare_business_chat",
    "stream_business_reply",
]

logger = logging.getLogger(__name__)

BUSINESS_SESSION_TYPE = "business"


@dataclass(slots=True)
class BusinessPlan:
    """一次业务问答所需的全部上下文，只带值类型。

    与 :class:`app.services.ai_service.ChatPlan` 一样不带 ORM 对象：生成器运行在
    响应阶段，请求级会话已经被 FastAPI 清理，拿对象会踩到"会话已关闭"。
    """

    session_id: int
    user_id: int
    role: str
    question: str
    masked_question: str
    masked: bool = False
    mask_hits: dict[str, int] = field(default_factory=dict)
    history: list[Message] = field(default_factory=list)
    as_of: str = ""
    context_text: str = ""
    context_items: list[dict[str, Any]] = field(default_factory=list)
    context_scope: str = ""
    context_counts: dict[str, int] = field(default_factory=dict)
    context_truncated: bool = False
    is_new_session: bool = False

    @property
    def has_data(self) -> bool:
        return bool(self.context_text)


async def prepare_business_chat(
    db: AsyncSession, user: User, payload: BusinessChatIn
) -> BusinessPlan:
    """校验/新建业务会话、落库用户消息、取业务快照。

    在返回流式响应之前执行，抛出的 404/403 能被全局异常处理器转成正常状态码。
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
        if session.type != BUSINESS_SESSION_TYPE:
            # 法律问答的会话混进来会带着法条引用，业务侧既不会用也没法解释
            raise NotFound("该会话不属于「AI督办」")
        history = await _load_history(db, session.id)
    else:
        session = AiSession(
            user_id=user.id,
            type=BUSINESS_SESSION_TYPE,
            title=_make_title(question),
        )
        db.add(session)
        await db.flush()

    db.add(AiMessage(session_id=session.id, role="user", content=question))
    session.updated_at = datetime.now()
    await db.commit()

    masked = mask_sensitive(question)
    if masked.masked:
        logger.info("业务问答已脱敏：%s（session=%s）", masked.summary, session.id)

    snapshot = await personal_context_service.build_business_snapshot(db, user)
    if snapshot.ok:
        logger.info(
            "业务快照 | user=%s(%s) | %d 字 | 条目 %d",
            user.username,
            user.role,
            snapshot.chars,
            len(snapshot.items),
        )

    return BusinessPlan(
        session_id=session.id,
        user_id=user.id,
        role=user.role,
        question=question,
        masked_question=masked.text,
        masked=masked.masked,
        mask_hits=masked.hits,
        history=history,
        as_of=snapshot.as_of,
        context_text=snapshot.text,
        context_items=snapshot.items,
        context_scope=snapshot.scope,
        context_counts=snapshot.counts,
        context_truncated=snapshot.truncated,
        is_new_session=is_new,
    )


async def stream_business_reply(plan: BusinessPlan) -> AsyncIterator[str]:
    """生成 SSE 事件流。**不要**把异常抛到外层——响应头已经发出，只能走 error。"""
    gateway = get_gateway()
    started = time.perf_counter()

    yield sse(
        "meta",
        {
            "session_id": plan.session_id,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "masked": plan.masked,
            "mask_hits": plan.mask_hits,
            "disclaimer": business_prompts.BUSINESS_DISCLAIMER,
        },
    )

    # 数据来源先推给前端：用户能立刻看到"读了哪几条"，也便于发现权限问题
    if plan.context_text:
        yield sse(
            "context",
            {
                "scope": plan.context_scope,
                "as_of": plan.as_of,
                "items": plan.context_items,
                "counts": plan.context_counts,
                "truncated": plan.context_truncated,
                "chars": len(plan.context_text),
            },
        )

    try:
        gateway.check_ready()
    except LLMError as exc:
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
        return

    if not plan.context_text:
        # 取数失败时不能装作在查：模型手里没有台账，硬答必然是编的
        yield sse(
            "error",
            {
                "detail": "业务数据暂时读不到，请稍后重试或直接查看对应页面",
                "retryable": True,
            },
        )
        return

    yield sse("stage", {"stage": "reading", "message": "正在读取你的案件与费用…"})
    yield sse("stage", {"stage": "generating", "message": "正在整理答复…"})

    messages = business_prompts.build_business_messages(
        plan.masked_question,
        plan.context_text,
        as_of=plan.as_of,
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
            yield sse("error", {"detail": "AI 未返回内容，请重试", "retryable": True})
            return

        token_usage = prompt_tokens + estimate_tokens(content)
        message_id = await sink.finalize([], token_usage)

        yield sse(
            "done",
            {
                "session_id": plan.session_id,
                "message_id": message_id,
                "token_usage": token_usage,
                "elapsed_ms": int((time.perf_counter() - started) * 1000),
                "as_of": plan.as_of,
                "disclaimer": business_prompts.BUSINESS_DISCLAIMER,
            },
        )
        logger.info(
            "业务问答完成 | session=%s | 用量约 %d token | %.1fs",
            plan.session_id,
            token_usage,
            time.perf_counter() - started,
        )
    except LLMError as exc:
        logger.warning("业务问答失败（session=%s）：%s", plan.session_id, exc)
        if sink.started:
            await sink.finalize(
                [],
                prompt_tokens + estimate_tokens(sink.content),
                note="（回答因 AI 服务异常中断，以上内容不完整）",
            )
        yield sse("error", {"detail": exc.friendly, "retryable": exc.retryable})
    except asyncio.CancelledError:
        logger.info(
            "客户端断开（session=%s），已保留 %d 字",
            plan.session_id,
            len(sink.content),
        )
        raise
    except Exception:  # 兜底：流式响应已开始，不能再让异常冒出去
        logger.exception("业务问答异常（session=%s）", plan.session_id)
        if sink.started:
            await sink.finalize(
                [],
                prompt_tokens + estimate_tokens(sink.content),
                note="（回答因系统异常中断，以上内容不完整）",
            )
        yield sse("error", {"detail": "AI 服务异常，请稍后重试", "retryable": True})
    finally:
        await sink.close()
