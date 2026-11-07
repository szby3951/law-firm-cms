"""OpenAI 兼容协议的 LLM 客户端。

DeepSeek、通义千问、Moonshot、智谱、vLLM、Ollama 都提供
``POST {base_url}/chat/completions`` 的 OpenAI 兼容接口，差别只在
``base_url`` / ``model`` / ``api_key``，所以 9.2.3 的「可扩展层」当前不需要为每家
写一个客户端——换供应商只改 ``.env``。

流式响应的报文形如::

    data: {"choices":[{"delta":{"content":"违"}}]}
    data: {"choices":[{"delta":{"content":"约"}}]}
    data: [DONE]

这里按行解析 ``data:`` 前缀，跳过注释行与空行；``usage`` 之类的收尾块没有
``choices``，直接忽略。
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Sequence
from typing import Any

import httpx

from app.ai.http_client import build_async_client
from app.ai.llm_clients.base import BaseLLMClient, LLMError, Message

logger = logging.getLogger(__name__)

# 这些状态码代表「上游暂时不可用」，值得退避重试
RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}


class _RetryableFailure(Exception):
    """内部信号：失败发生在首个 token 之前，可以安全重试。"""

    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class OpenAICompatibleClient(BaseLLMClient):
    """基于 httpx 的 OpenAI 兼容客户端，支持流式、JSON 与探活。"""

    provider = "openai"

    # ---------- 内部工具 ----------

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise LLMError(
                "未配置 LLM_API_KEY，AI 功能不可用",
                friendly="AI 服务尚未配置，请联系管理员",
            )
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }

    def _timeout(self) -> httpx.Timeout:
        """连接超时短、读超时长。

        流式响应每收到一个 token 都会重置读超时，因此 ``read`` 只需覆盖「两个
        token 之间的最大间隔」；但非流式（如 JSON 生成）在收齐前没有任何字节，
        仍需按 ``llm_timeout`` 给足。
        """
        return httpx.Timeout(
            connect=10.0, read=float(self.timeout), write=30.0, pool=10.0
        )

    def _client(self) -> httpx.AsyncClient:
        # 统一走 build_async_client：不继承 HTTP_PROXY，代理只认 OUTBOUND_PROXY。
        # 早先按 base_url 是否本机来决定 trust_env，结果公网调用会继承开发机
        # 临时代理，代理一停就抛 httpx.ReadTimeout，看起来像大模型挂了。
        return build_async_client(timeout=self._timeout())

    def _payload(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        stream: bool,
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": list(messages),
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
            "stream": stream,
        }
        if response_format:
            payload["response_format"] = response_format
        if self.enable_thinking is not None:
            # 只有「混合思考」模型认这个字段；DeepSeek 等不认的供应商传了会 400，
            # 因此由 LLM_ENABLE_THINKING 控制，默认 auto 不下发。
            payload["enable_thinking"] = self.enable_thinking
        return payload

    @staticmethod
    def _error_message(status: int, body: str) -> str:
        try:
            detail = json.loads(body)
            if isinstance(detail, dict):
                err = detail.get("error")
                if isinstance(err, dict) and err.get("message"):
                    return str(err["message"])[:300]
                if detail.get("message"):
                    return str(detail["message"])[:300]
        except (json.JSONDecodeError, TypeError):
            pass
        return body.strip()[:300] or f"HTTP {status}"

    def _raise_for_status(self, status: int, body: str) -> None:
        """把 HTTP 状态翻译成带中文诊断的异常，区分可重试与否。"""
        message = self._error_message(status, body)
        if status in RETRYABLE_STATUS:
            raise _RetryableFailure(f"上游返回 {status}：{message}", status_code=status)
        if status in (401, 403):
            raise LLMError(
                f"鉴权失败（HTTP {status}）：{message}。请检查 LLM_API_KEY 是否正确",
                status_code=status,
                friendly="AI 服务鉴权失败，请联系管理员",
            )
        if status == 404:
            raise LLMError(
                f"接口不存在（HTTP 404）：{message}。请检查 LLM_BASE_URL 是否以 /v1 结尾",
                status_code=status,
                friendly="AI 服务地址配置有误，请联系管理员",
            )
        if status == 400 and self.enable_thinking is not None and "thinking" in body:
            # 典型场景：把 LLM_MODEL 换成不支持该字段的模型（如 qwen-max）却仍开着开关。
            # 直接说清楚要改哪一项，否则只看到一个笼统的 400 很难排查。
            raise LLMError(
                f"模型 {self.model} 不接受 enable_thinking 参数：{message}。"
                "请把 .env 的 LLM_ENABLE_THINKING 改为 auto",
                status_code=status,
                friendly="AI 服务配置有误，请联系管理员",
            )
        raise LLMError(f"请求被拒绝（HTTP {status}）：{message}", status_code=status)

    # ---------- 流式 ----------

    async def _stream_once(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None,
        max_tokens: int | None,
        response_format: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        url = f"{self.base_url}/chat/completions"
        payload = self._payload(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            response_format=response_format,
        )
        headers = self._headers()

        try:
            # 客户端创建/关闭也放在 try 内：代理链路异常时，异常可能在
            # 连接池 aclose() 阶段才抛出，而不是在 stream() 里；
            # 漏出去就变成未捕获的 ASGI 500，前端只看到「系统异常」。
            async with self._client() as client, client.stream(
                "POST", url, headers=headers, json=payload
            ) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "ignore")
                    self._raise_for_status(resp.status_code, body)

                async for line in resp.aiter_lines():
                    piece = self._parse_line(line)
                    if piece is _DONE:
                        return
                    if piece:
                        yield piece
        except httpx.TimeoutException as exc:
            raise _RetryableFailure(
                f"调用大模型超时（{self.timeout}s 无响应）"
            ) from exc
        except httpx.HTTPError as exc:
            # 可能是首字节前的连接错误（可重试），也可能是流中间断开（不可重试）。
            raise _RetryableFailure(f"连接大模型失败：{exc}") from exc

    @staticmethod
    def _parse_line(line: str) -> str | None | _Done:
        """解析一行 SSE，返回文本增量、``None``（无内容）或 ``_DONE`` 哨兵。"""
        line = line.strip()
        if not line or line.startswith(":"):
            return None
        if not line.startswith("data:"):
            return None
        data = line[5:].strip()
        if data == "[DONE]":
            return _DONE
        try:
            chunk = json.loads(data)
        except json.JSONDecodeError:
            # 个别服务会插入心跳或非 JSON 数据，跳过而不是让整段对话失败
            logger.debug("无法解析的流式分片：%s", data[:80])
            return None
        if isinstance(chunk, dict) and chunk.get("error"):
            err = chunk["error"]
            message = err.get("message") if isinstance(err, dict) else str(err)
            raise LLMError(f"上游在流式响应中返回错误：{message}")
        choices = chunk.get("choices") or []
        if not choices:
            return None
        delta = choices[0].get("delta") or {}
        content = delta.get("content")
        return content or None

    async def stream_chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """逐段输出文本增量（带首 token 前的重试）。"""
        async for piece in self._stream_with_retry(
            messages, temperature=temperature, max_tokens=max_tokens
        ):
            yield piece

    async def _stream_with_retry(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> AsyncIterator[str]:
        """带重试的流式请求，供普通对话与 JSON 模式共用。

        重试只发生在首个 token 之前（连接失败、429、5xx）。一旦已经吐过内容，
        重试会造成重复文本，此时直接把错误抛给上层，由前端提示「生成中断」。

        ``_RetryableFailure`` 是内部信号，**绝不能**泄漏到业务层：调用方只认
        :class:`LLMError`（``friendly``/``retryable`` 才有意义）。JSON 模式早先
        直接调 ``_stream_once``，导致上游 5xx 会以未捕获的内部异常冒到服务层，
        被当成"系统异常"而不是"AI 服务不可用"。
        """
        attempts = max(1, self.max_retries + 1)
        last_failure: _RetryableFailure | None = None

        for attempt in range(attempts):
            started = False
            try:
                async for piece in self._stream_once(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format=response_format,
                ):
                    started = True
                    yield piece
                return
            except _RetryableFailure as exc:
                last_failure = exc
                if started:
                    raise LLMError(f"流式输出中断：{exc}", retryable=True) from exc
                if attempt < attempts - 1:
                    delay = 2**attempt
                    logger.warning(
                        "大模型调用失败（第 %d/%d 次），%ss 后重试：%s",
                        attempt + 1,
                        attempts,
                        delay,
                        exc,
                    )
                    await asyncio.sleep(delay)

        detail = str(last_failure) if last_failure else "未知错误"
        raise LLMError(
            f"调用大模型失败（已重试 {attempts - 1} 次）：{detail}",
            retryable=True,
            status_code=last_failure.status_code if last_failure else None,
        ) from last_failure

    # ---------- JSON ----------

    async def _json_completion(
        self, messages: Sequence[Message], *, max_tokens: int | None = None
    ) -> str:
        """优先用 ``response_format=json_object``；上游不支持时自动退回提示词约束。"""
        limit = self.max_tokens if max_tokens is None else max_tokens
        try:
            parts = [
                part
                async for part in self._stream_with_retry(
                    messages,
                    temperature=0,
                    max_tokens=limit,
                    response_format={"type": "json_object"},
                )
            ]
            return "".join(parts)
        except LLMError as exc:
            if exc.status_code != 400:
                raise
            logger.info("上游不支持 response_format，改用提示词约束：%s", exc)

        parts = [
            part
            async for part in self._stream_with_retry(
                messages, temperature=0, max_tokens=limit
            )
        ]
        return "".join(parts)

    # ---------- 探活 ----------

    async def health(self) -> dict[str, Any]:
        info: dict[str, Any] = {
            "ok": False,
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
        }
        if not self.api_key:
            info["error"] = "未配置 LLM_API_KEY"
            return info
        try:
            async with self._client() as client:
                resp = await client.get(
                    f"{self.base_url}/models",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    timeout=10,
                )
            info["status"] = resp.status_code
            if resp.status_code == 200:
                info["ok"] = True
                try:
                    data = resp.json()
                    info["models"] = [m.get("id") for m in data.get("data", [])][:20]
                except (json.JSONDecodeError, AttributeError, TypeError):
                    pass
            else:
                info["error"] = self._error_message(resp.status_code, resp.text)
        except httpx.HTTPError as exc:
            info["error"] = f"{exc.__class__.__name__}: 无法连接 {self.base_url}"
        return info


class _Done:
    """``[DONE]`` 哨兵，用独立对象避免与文本内容混淆。"""


_DONE = _Done()
