"""AIGateway：模块9 的统一模型入口（任务拆解 9.2.1）。

业务代码（9.3 RAG、9.4 文书、9.5 审查、9.6 摘要、9.7 画像、9.8 前端接口）
一律只依赖这个门面，不直接 import 具体客户端。这样：

- 换供应商只改 ``.env``，业务代码零改动（9.2.4）；
- 降级逻辑集中在一处，不会出现「某个功能挂了整个页面 500」；
- 之后要给对话加限流、用量统计、脱敏，只需在这里加一层，不必改十几个调用点。

三个核心方法对应 9.2.1 的约定：

============  ==============================================
``chat``      流式对话，逐段 yield 文本，供 SSE 直接转发
``generate_json``  要求模型输出 JSON（文书结构、审查报告、客户画像）
``embed``     文本向量化，委托给 embedding 客户端（云端/本地 TEI 均可）
============  ==============================================
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

from app.ai import embedding
from app.ai.llm_clients import BaseLLMClient, create_client
from app.ai.llm_clients.base import (
    FRIENDLY_UNAVAILABLE,
    LLMError,
    Message,
    build_messages,
)
from app.config import settings

logger = logging.getLogger(__name__)

__all__ = ["AIGateway", "LLMError", "gateway", "get_gateway"]


class AIGateway:
    """模型接入层门面。

    :param client: 可注入客户端，缺省按 ``settings`` 懒加载；测试时可传入假客户端
    """

    def __init__(self, client: BaseLLMClient | None = None):
        self._client = client

    # ---------- 状态 ----------

    @property
    def enabled(self) -> bool:
        """是否配置了 API Key。未配置时 AI 功能整体降级，不影响主系统。"""
        return settings.llm_enabled

    @property
    def client(self) -> BaseLLMClient:
        if self._client is None:
            self._client = create_client()
        return self._client

    def describe(self) -> dict[str, Any]:
        """对外暴露的配置快照，**不含 API Key**，供管理端展示或排查用。"""
        return {
            "enabled": self.enabled,
            "provider": settings.llm_provider,
            "model": settings.llm_model,
            "base_url": settings.llm_base_url,
            "temperature": settings.llm_temperature,
            "max_tokens": settings.llm_max_tokens,
            "timeout": settings.llm_timeout,
            "max_retries": settings.llm_max_retries,
            "enable_thinking": settings.llm_enable_thinking,
        }

    def _ensure_enabled(self) -> None:
        if not self.enabled:
            raise LLMError(
                "未配置 LLM_API_KEY，AI 功能不可用",
                friendly="AI 服务尚未配置，请联系管理员",
            )
        if not settings.llm_base_url.strip():
            raise LLMError(
                "未配置 LLM_BASE_URL，AI 功能不可用",
                friendly="AI 服务尚未配置，请联系管理员",
            )

    def check_ready(self) -> None:
        """只做「配置是否齐全」的检查，不发起网络请求。

        供上层在**开始检索之前**快速失败：未配置 Key 时没必要先跑一遍向量
        检索再报错，用户会先看到"正在检索法条"再看到"服务未配置"，白等两秒。
        """
        self._ensure_enabled()

    # ---------- 对话 ----------

    async def chat(
        self,
        messages: Sequence[Message] | str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        fallback: str | bool | None = None,
    ) -> AsyncIterator[str]:
        """流式对话，逐段输出文本增量。

        :param system: 系统提示词，会自动插到消息列表最前
        :param fallback: 降级策略。只在**首个 token 之前**失败时生效（未配置
            Key、连不上、上游 5xx）：

            - ``None``/``False``：抛 :class:`LLMError`，由接口层返回 503；
            - ``True``：输出 ``exc.friendly``（按失败原因区分配置错误 / 暂时不可用）；
            - 字符串：输出该文案（调用方自定义）。

            前端已建立 SSE 连接时，输出一句话比直接断流更友好；但如果已经吐过
            部分内容，仍会抛异常——此时内容不完整，必须由前端标记「生成中断」，
            否则用户会把半句话当成完整答案。
        """
        try:
            self._ensure_enabled()
        except LLMError as exc:
            text = self._fallback_text(fallback, exc)
            if text is None:
                raise
            logger.warning("AI 对话降级：%s", exc)
            yield text
            return

        started = False
        try:
            async for piece in self.client.stream_chat(
                build_messages(messages, system=system),
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                started = True
                yield piece
        except LLMError as exc:
            text = self._fallback_text(fallback, exc)
            if text is not None and not started:
                logger.warning("AI 对话失败，返回降级文案：%s", exc)
                yield text
                return
            raise

    @staticmethod
    def _fallback_text(fallback: str | bool | None, exc: LLMError) -> str | None:
        """把 fallback 参数解析成实际要输出的文案；``None`` 表示继续抛异常。"""
        if fallback is True:
            return exc.friendly
        if isinstance(fallback, str):
            return fallback
        return None

    async def complete(
        self,
        messages: Sequence[Message] | str,
        *,
        system: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """非流式对话，收齐后一次性返回（用于内部加工，如摘要再渲染）。"""
        self._ensure_enabled()
        return await self.client.complete(
            build_messages(messages, system=system),
            temperature=temperature,
            max_tokens=max_tokens,
        )

    # ---------- 结构化输出 ----------

    async def generate_json(
        self,
        messages: Sequence[Message] | str,
        *,
        schema_hint: str | None = None,
        system: str | None = None,
        retries: int = 1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """要求模型输出 JSON 对象并解析为 dict。

        :param schema_hint: 字段说明，例如
            ``'{"level": "high|mid|low", "risks": [{"clause": "...", "advice": "..."}]}'``
        :param retries: 解析失败时追加纠正的次数
        :param max_tokens: 单次输出上限，结构化长报告需要比默认值更宽
        :raises LLMError: 未配置 Key、调用失败，或多次仍无法解析
        """
        self._ensure_enabled()
        return await self.client.generate_json(
            messages,
            schema_hint=schema_hint,
            system=system,
            retries=retries,
            max_tokens=max_tokens,
        )

    # ---------- 向量化 ----------

    async def embed(
        self,
        texts: list[str],
        *,
        batch_size: int | None = None,
        concurrency: int | None = None,
        progress: object | None = None,
    ) -> list[list[float]]:
        """批量向量化，委托 :mod:`app.ai.embedding`（云端接口或本地 TEI）。

        失败抛 :class:`~app.ai.embedding.EmbeddingError`，与 9.1 的降级链路一致。
        """
        return await embedding.embed_texts(
            texts,
            batch_size=batch_size,
            concurrency=concurrency,
            progress=progress,
        )

    async def embed_query(self, text: str) -> list[float]:
        """问题向量化（与法条入库使用同一模型，保证可比较）。"""
        return await embedding.embed_query(text)

    # ---------- 探活 ----------

    async def health(self) -> dict[str, Any]:
        """同时探测大模型与向量服务，返回整体状态。

        ``ok`` 只在两者都可用时为 True；未配置 Key 时 ``llm.ok=False`` 并给出原因，
        但不会抛异常——管理端要能展示「为什么不可用」。
        """
        llm: dict[str, Any]
        if not self.enabled:
            llm = {
                "ok": False,
                "provider": settings.llm_provider,
                "model": settings.llm_model,
                "base_url": settings.llm_base_url,
                "error": "未配置 LLM_API_KEY",
            }
        else:
            try:
                llm = await self.client.health()
            except LLMError as exc:
                llm = {
                    "ok": False,
                    "provider": settings.llm_provider,
                    "model": settings.llm_model,
                    "error": str(exc),
                }

        vector = await embedding.check_health()
        return {
            "ok": bool(llm.get("ok")) and bool(vector.get("ok")),
            "llm": llm,
            "embedding": vector,
        }

    # ---------- 降级约定 ----------

    @staticmethod
    def friendly_message() -> str:
        """统一的降级文案，供接口层/前端兜底使用。"""
        return FRIENDLY_UNAVAILABLE


_gateway = AIGateway()


def get_gateway() -> AIGateway:
    """获取全局门面实例。

    门面自身无状态（客户端懒加载），因此不需要每次重建；测试时可直接
    ``AIGateway(client=FakeClient())`` 注入。
    """
    return _gateway


gateway = _gateway
