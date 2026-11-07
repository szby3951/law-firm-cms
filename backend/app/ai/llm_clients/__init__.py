"""LLM 客户端注册表。

上层只调用 :func:`create_client`，按下述顺序决定用哪个客户端：

1. 显式传入 ``provider``（用于测试或灰度）；
2. ``settings.llm_provider``（``.env`` 的 ``LLM_PROVIDER``）；
3. 兜底 ``"openai"``。

新增供应商的两条路：

- **协议兼容**（绝大多数）：服务商提供 ``/chat/completions``，只需在下方
  ``ALIASES`` 里登记别名，或直接用 ``LLM_PROVIDER=openai``，无需写代码；
- **私有协议**（如某些本地推理框架）：新建 ``xxx_client.py``，继承
  :class:`~app.ai.llm_clients.base.BaseLLMClient` 并打上 :func:`register_client`
  装饰器，然后在 ``app.ai.llm_clients`` 里 import 一次即可被自动发现。
"""

from __future__ import annotations

from typing import Any

from app.ai.llm_clients.base import BaseLLMClient, LLMError, Message
from app.ai.llm_clients.openai_client import OpenAICompatibleClient
from app.config import settings

__all__ = [
    "BaseLLMClient",
    "LLMError",
    "Message",
    "OpenAICompatibleClient",
    "available_providers",
    "create_client",
    "register_client",
]

_REGISTRY: dict[str, type[BaseLLMClient]] = {}

# 采用 OpenAI 兼容协议的服务商别名。它们的行为完全一致，区别仅在 base_url。
ALIASES: dict[str, str] = {
    "openai": "openai",
    "deepseek": "openai",
    "qwen": "openai",
    "dashscope": "openai",
    "moonshot": "openai",
    "zhipu": "openai",
    "siliconflow": "openai",
    "ollama": "openai",
    "vllm": "openai",
    "lmstudio": "openai",
    "openai-compatible": "openai",
    "compatible": "openai",
}


def register_client(*providers: str):
    """类装饰器：把客户端登记到一个或多个供应商名上。"""

    def decorator(cls: type[BaseLLMClient]) -> type[BaseLLMClient]:
        for name in providers:
            _REGISTRY[name.lower()] = cls
        return cls

    return decorator


register_client("openai")(OpenAICompatibleClient)


def available_providers() -> list[str]:
    """已注册的供应商名（含别名），供管理端下拉框或排查用。"""
    return sorted(set(_REGISTRY) | set(ALIASES))


def create_client(
    provider: str | None = None,
    **overrides: Any,
) -> BaseLLMClient:
    """按配置构造客户端。

    :param provider: 供应商名，缺省取 ``settings.llm_provider``
    :param overrides: 覆盖任一构造参数（测试时用来指定 base_url / api_key）
    :raises LLMError: 供应商未注册
    """
    name = (provider or settings.llm_provider or "openai").strip().lower()
    key = ALIASES.get(name, name)
    cls = _REGISTRY.get(key)
    if cls is None:
        raise LLMError(
            f"未支持的模型供应商：{name}，可选 {', '.join(available_providers())}",
            friendly="AI 服务配置有误，请联系管理员",
        )

    params: dict[str, Any] = {
        "base_url": settings.llm_base_url,
        "api_key": settings.llm_api_key,
        "model": settings.llm_model,
        "temperature": settings.llm_temperature,
        "max_tokens": settings.llm_max_tokens,
        "timeout": settings.llm_timeout,
        "max_retries": settings.llm_max_retries,
        "enable_thinking": settings.llm_thinking_flag,
    }
    params.update(overrides)
    client = cls(**params)
    # 记录用户实际填写的供应商名，便于 health / 日志区分（如 deepseek 与 openai
    # 走同一份实现，但配置来源不同）
    client.provider = name
    return client
