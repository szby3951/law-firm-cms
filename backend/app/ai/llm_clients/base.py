"""LLM 客户端基类与异常定义。

模块9 的所有大模型调用都经过这里，目的有三个：

1. **统一异常语义**：无论底层是 DeepSeek、通义还是本地 vLLM，上层只认
   :class:`LLMError`，由 ``main.py`` 统一转成 503 友好提示（任务拆解 9.9.4），
   主系统不会因为模型挂掉而看到 500。
2. **统一消息格式**：只用 OpenAI 的 ``{"role", "content"}`` 结构，避免每个
   供应商各写一套。新增供应商时继承 :class:`BaseLLMClient` 即可（9.2.3）。
3. **把「重试」限定在安全的位置**：流式响应一旦开始吐出 token 就不能重试
   （会导致前端重复收到内容），所以重试只发生在建立连接、拿到响应头之前。
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Sequence
from typing import Any, Literal, TypedDict

# 面向用户的统一降级文案：不暴露 base_url、状态码、密钥等内部细节
FRIENDLY_UNAVAILABLE = "AI 服务暂时不可用，请稍后重试"


class Message(TypedDict):
    """一条对话消息，与 OpenAI Chat Completions 的字段对齐。"""

    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(RuntimeError):
    """大模型调用失败。

    :param message: 面向开发者的诊断信息（会写日志，不直接给用户看）
    :param retryable: 是否属于「稍后重试可能成功」（超时/限流/5xx 为 True，
        鉴权失败、参数错误为 False），供上层决定是否提示用户重试
    :param status_code: 上游 HTTP 状态码，便于排查
    """

    def __init__(
        self,
        message: str,
        *,
        retryable: bool = False,
        status_code: int | None = None,
        friendly: str = FRIENDLY_UNAVAILABLE,
    ):
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code
        self.friendly = friendly


def build_messages(
    messages: Sequence[Message] | str,
    *,
    system: str | None = None,
) -> list[Message]:
    """把「一段文本 / 消息列表 + 可选 system」规范成消息列表。

    上层调用时常图省事直接传一句话，这里统一兜住；若列表首条已是 system，
    则不再重复插入，避免出现两个 system 提示词。
    """
    if isinstance(messages, str):
        items: list[Message] = [{"role": "user", "content": messages}]
    else:
        items = [dict(m) for m in messages]  # type: ignore[misc]

    if system and not (items and items[0].get("role") == "system"):
        items.insert(0, {"role": "system", "content": system})
    return items


def _strip_code_fence(text: str) -> str:
    """去掉 ```json ... ``` 包裹，模型经常不听话地加上。"""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    lines = stripped.splitlines()
    if lines and lines[0].startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip().startswith("```"):
        lines = lines[:-1]
    return "\n".join(lines).strip()


def extract_json(text: str) -> dict[str, Any] | None:
    """从模型输出里尽力抠出一个 JSON 对象，失败返回 ``None``。

    模型常见毛病是「先解释两句再给 JSON」，所以按 ``{`` 的位置逐个尝试
    ``raw_decode``（能正确处理嵌套与字符串里的括号），而不是简单截取首尾大括号。
    """
    if not text:
        return None
    candidate = _strip_code_fence(text)
    try:
        data = json.loads(candidate)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    index = candidate.find("{")
    while index >= 0:
        try:
            data, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            index = candidate.find("{", index + 1)
            continue
        if isinstance(data, dict):
            return data
        index = candidate.find("{", index + 1)
    return None


class BaseLLMClient(ABC):
    """大模型客户端抽象基类。

    子类只需实现 :meth:`stream_chat` 与 :meth:`health`；:meth:`complete`、
    :meth:`generate_json` 已有通用实现，必要时可覆写（例如让请求带上
    ``response_format``）。
    """

    provider: str = "openai"

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        timeout: int = 60,
        max_retries: int = 2,
        enable_thinking: bool | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.max_retries = max_retries
        # 混合思考模型的思维链开关：None = 不下发，用供应商默认值。
        # 思维链会占用 max_tokens 预算且首字明显变慢（实测关闭后首字 3.1s → 1.1s），
        # 法条问答这类「要结论不要推理过程」的场景建议关闭。
        self.enable_thinking = enable_thinking

    @abstractmethod
    def stream_chat(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """流式对话，逐段 ``yield`` 文本增量（不含空串）。"""

    async def _json_completion(
        self, messages: Sequence[Message], *, max_tokens: int | None = None
    ) -> str:
        """产出 JSON 的原始文本，子类可覆写以附加 ``response_format``。"""
        parts = [
            part
            async for part in self.stream_chat(
                messages,
                temperature=0,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            )
        ]
        return "".join(parts)

    async def complete(
        self,
        messages: Sequence[Message],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """非流式调用：内部仍走流式，收齐后一次性返回。

        好处是流式链路只维护一份，避免「流式」和「非流式」两套代码行为不一致。
        """
        parts = [
            part
            async for part in self.stream_chat(
                messages, temperature=temperature, max_tokens=max_tokens
            )
        ]
        return "".join(parts).strip()

    async def generate_json(
        self,
        messages: Sequence[Message] | str,
        *,
        schema_hint: str | None = None,
        system: str | None = None,
        retries: int = 1,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        """要求模型输出 JSON 并解析成 dict。

        :param schema_hint: 期望的字段说明（写进提示词，能显著提高合规率）
        :param retries: 解析失败后的追加纠正次数，每次把上次原文回灌给模型
        :param max_tokens: 单次输出上限。结构化报告（如合同审查的 8~10 条风险）
            很容易超过默认的 2048，被截断的 JSON 解析必然失败，此时要单独放宽。
        """
        base = build_messages(messages, system=system)
        instruction = (
            "请只输出一个合法的 JSON 对象，不要输出 Markdown 代码块或任何解释。"
        )
        if schema_hint:
            instruction += f"\n字段要求：{schema_hint}"
        base = base + [{"role": "user", "content": instruction}]

        attempt_messages = list(base)
        last_raw = ""
        for attempt in range(retries + 1):
            last_raw = await self._json_completion(
                attempt_messages, max_tokens=max_tokens
            )
            data = extract_json(last_raw)
            if data is not None:
                return data
            if attempt < retries:
                attempt_messages = [
                    *base,
                    {"role": "assistant", "content": last_raw[:1000]},
                    {
                        "role": "user",
                        "content": "上面的输出无法被 JSON 解析。请重新输出，"
                        "只输出一个合法 JSON 对象，不要任何解释。",
                    },
                ]

        snippet = last_raw.strip()[:160].replace("\n", " ")
        raise LLMError(
            f"模型未返回合法 JSON，原始输出：{snippet}",
            friendly="AI 返回结果格式异常，请重试",
        )

    @abstractmethod
    async def health(self) -> dict[str, Any]:
        """探活，返回 ``{ok, provider, model, base_url, ...}``，不抛异常。"""
