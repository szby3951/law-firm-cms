"""出站 HTTP 客户端的统一构造入口。

**为什么需要这个模块。** httpx 默认 ``trust_env=True``，会自动读取进程环境里的
``HTTP_PROXY`` / ``HTTPS_PROXY`` / ``ALL_PROXY``。后端通常由某个终端、IDE 或脚本
拉起，很容易连带继承开发机上临时的代理配置（例如本机调试用的 127.0.0.1:7890），
于是：

- 代理没开 → 所有模型调用变成 ``ConnectError``；
- 代理开着一会儿就关 → 连接建立后收不到响应头，抛 ``ReadTimeout`` /
  ``RemoteProtocolError``，堆栈里出现 ``httpcore/_async/http_proxy.py``；
- 本地 TEI / Qdrant 请求被转发到代理，绕了一圈再失败。

表现出来就是「AI 服务突然 500」，但大模型与向量服务其实都是好的。

**约定。** 默认 ``trust_env=False``，即完全不认环境变量；需要走代理时用
``OUTBOUND_PROXY`` 显式配置（例如 ``http://127.0.0.1:7890``），只有它会被使用。
这样「代理」从隐式继承变成一份可审查的配置，出问题能一眼看到。
"""

from __future__ import annotations

import os
from typing import Final

import httpx

from app.config import settings

__all__ = ["build_async_client", "describe_proxy", "ignored_env_proxies"]

# httpx 读取的代理环境变量名（大小写各一份）
_PROXY_ENV_KEYS: Final = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)


def ignored_env_proxies() -> dict[str, str]:
    """返回被忽略的代理环境变量，供启动日志提示用。"""
    found: dict[str, str] = {}
    for key in _PROXY_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            found[key] = value
    return found


def describe_proxy() -> str:
    """人类可读的代理状态：``直连`` 或具体代理地址。"""
    return settings.outbound_proxy.strip() or "直连（忽略系统代理环境变量）"


def build_async_client(
    *,
    timeout: float | httpx.Timeout,
    proxy: str | None = None,
    follow_redirects: bool = False,
) -> httpx.AsyncClient:
    """创建一个不继承系统代理的 httpx 客户端。

    :param timeout: 超时设置，数值或 :class:`httpx.Timeout`
    :param proxy: 显式代理地址；缺省用 ``OUTBOUND_PROXY``，仍为空则直连
    :param follow_redirects: 是否跟随重定向（下载型请求才需要）
    """
    effective = (proxy if proxy is not None else settings.outbound_proxy).strip()
    return httpx.AsyncClient(
        timeout=timeout,
        proxy=effective or None,
        trust_env=False,
        follow_redirects=follow_redirects,
    )
