"""向量化客户端：支持「云端 OpenAI 兼容接口」与「本地 TEI」两种后端。

模块9 的 RAG 需要把条文/知识片段转成向量。这里不直接依赖 ``sentence-transformers``，
而是在进程外完成向量化，主服务只负责收发 HTTP：

- ``EMBEDDING_PROVIDER=openai``（默认）：``POST {base_url}/embeddings``，
  适配 DashScope ``text-embedding-v3/v4``、SiliconFlow ``bge-m3`` 等所有
  OpenAI 兼容服务。**2C2G 服务器推荐这一档**——本地跑 bge-large 要 1.4~1.8GB
  内存，和 MySQL/Qdrant 挤在一起必然 OOM。
- ``EMBEDDING_PROVIDER=tei``：``POST {base_url}/embed``，走自建的
  Text Embeddings Inference（``http://127.0.0.1:8081``）。适合有闲置内存、
  想完全离线部署的场景。

两种后端对外接口一致（:func:`embed_texts` / :func:`embed_query`），切换只改 .env。
服务不可用时统一抛 :class:`EmbeddingError`，由调用方降级为友好提示
（任务拆解 9.9.4：模型服务不可用时主系统不受影响）。

**换模型/换后端的代价**：向量空间不可比，必须 ``kb_builder.py --reset-vectors --reindex``
重建全部向量，否则新问题会在旧向量里检索，结果全是噪音。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

import httpx

from app.ai.http_client import build_async_client
from app.config import settings

logger = logging.getLogger(__name__)

# BGE 系列做「短查询 → 长文档」检索时的官方建议前缀（仅 TEI + bge 场景有意义）。
BGE_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："


class EmbeddingError(RuntimeError):
    """向量服务不可用或返回异常。"""


def _service_name() -> str:
    return "TEI 向量服务" if settings.embedding_provider == "tei" else "Embedding 接口"


def _headers() -> dict[str, str]:
    """云端接口的鉴权头；TEI 内网服务不需要。"""
    if settings.embedding_provider == "tei":
        return {}
    key = settings.embedding_key
    return {"Authorization": f"Bearer {key}"} if key else {}


def _normalize_payloads(data: object) -> list[list[float]]:
    """把各家的返回统一成 ``[[float, ...], ...]``，保持返回顺序。

    兼容三种形状：
    - OpenAI / DashScope → ``{"data": [{"embedding": [...], "index": 0}, ...]}``
    - TEI（json-output） → ``{"embeddings": [[...]]}``
    - TEI 默认 → 单条 ``[0.1, ...]``，多条 ``[[...], [...]]``
    """
    if isinstance(data, dict):
        data = data.get("data") or data.get("embeddings") or []
    if not isinstance(data, list):
        raise EmbeddingError("向量服务返回格式异常")
    if not data:
        return []
    first = data[0]
    if isinstance(first, (int, float)):
        return [[float(x) for x in data]]
    if isinstance(first, dict):
        # OpenAI 风格不保证数组顺序，带 index 时按 index 还原
        items = list(data)
        if all(isinstance(item.get("index"), int) for item in items):
            items.sort(key=lambda item: item["index"])
        return [[float(x) for x in item.get("embedding", [])] for item in items]
    return [[float(x) for x in item] for item in data]


async def _send_with_retry(
    send: Callable[[], Awaitable[httpx.Response]],
) -> httpx.Response:
    """发一次请求，对超时/连接失败/429/5xx 做退避重试。

    429 是云端接口最常见的失败（QPS 限流），必须单独处理：优先按
    ``Retry-After`` 等待，没有该头就指数退避。TEI 侧则是排队超时，同样适用。
    """
    attempts = 3
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            resp = await send()
        except httpx.TimeoutException as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            raise EmbeddingError(
                f"{_service_name()}响应超时（{settings.embedding_timeout}s），"
                "请稍后重试或调大 EMBEDDING_TIMEOUT"
            ) from exc
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(2 * (attempt + 1))
                continue
            raise EmbeddingError(
                f"{_service_name()}连接失败（{settings.embedding_base_url}），"
                "请检查地址、网络与 EMBEDDING_PROVIDER 配置"
            ) from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            last_error = EmbeddingError(
                f"{_service_name()}返回 {resp.status_code}：{resp.text[:200]}"
            )
            if attempt < attempts - 1:
                retry_after = resp.headers.get("Retry-After", "")
                delay = (
                    float(retry_after) if retry_after.isdigit() else 2.0 * (attempt + 1)
                )
                logger.warning(
                    "%s限流/异常 %s，%.1fs 后重试（%s/%s）",
                    _service_name(),
                    resp.status_code,
                    delay,
                    attempt + 1,
                    attempts,
                )
                await asyncio.sleep(min(delay, 10.0))
                continue
            raise last_error
        if resp.status_code == 413:
            raise EmbeddingError(
                "单条文本超出向量服务长度上限，请调小 EMBEDDING_MAX_CHARS"
            )
        if resp.status_code >= 400:
            raise EmbeddingError(
                f"{_service_name()}返回 {resp.status_code}：{resp.text[:200]}"
            )
        return resp

    raise EmbeddingError(str(last_error) if last_error else "向量服务调用失败")


async def _request_tei(
    client: httpx.AsyncClient, texts: list[str]
) -> list[list[float]]:
    url = f"{settings.embedding_base_url.rstrip('/')}/embed"

    async def send() -> httpx.Response:
        return await client.post(url, json={"inputs": texts, "normalize": True})

    resp = await _send_with_retry(send)
    return _normalize_payloads(resp.json())


async def _request_openai(
    client: httpx.AsyncClient, texts: list[str]
) -> list[list[float]]:
    """OpenAI 兼容 ``/embeddings``。``dimensions`` 部分服务商不支持，需自动回退。"""
    url = f"{settings.embedding_base_url.rstrip('/')}/embeddings"
    payload: dict[str, object] = {"model": settings.embedding_model, "input": texts}
    if settings.embedding_dim:
        payload["dimensions"] = settings.embedding_dim

    async def send() -> httpx.Response:
        return await client.post(url, json=payload, headers=_headers())

    try:
        resp = await _send_with_retry(send)
    except EmbeddingError as exc:
        # 部分自建/第三方服务不认 dimensions 参数（400 且提到 dimension），
        # 此时去掉该字段重试一次：维度由模型本身决定，能用即可（下游会校验维度）。
        text = str(exc)
        if "400" not in text or "dimension" not in text.lower():
            raise
        logger.warning(
            "服务商不接受 dimensions 参数，改用模型默认维度重试（请确认 EMBEDDING_DIM=%s）",
            settings.embedding_dim,
        )
        payload.pop("dimensions", None)
        resp = await _send_with_retry(send)
    return _normalize_payloads(resp.json())


async def _post_embed(client: httpx.AsyncClient, texts: list[str]) -> list[list[float]]:
    """按 provider 分发，并校验返回条数与维度。"""
    if settings.embedding_provider == "tei":
        vectors = await _request_tei(client, texts)
    else:
        vectors = await _request_openai(client, texts)

    if len(vectors) != len(texts):
        raise EmbeddingError(
            f"向量条数不匹配：送入 {len(texts)} 条，返回 {len(vectors)} 条"
        )
    for vec in vectors:
        if len(vec) != settings.embedding_dim:
            raise EmbeddingError(
                f"向量维度不匹配：模型返回 {len(vec)} 维，"
                f"配置 EMBEDDING_DIM={settings.embedding_dim}。"
                "请把 .env 的 EMBEDDING_DIM 改成实际维度后重建向量"
            )
    return vectors


async def embed_texts(
    texts: list[str],
    *,
    batch_size: int | None = None,
    concurrency: int | None = None,
    progress: object | None = None,
) -> list[list[float]]:
    """批量向量化，保持输入顺序。

    :param texts: 待向量化文本（调用方负责保证不超过 ``embedding_max_chars``）
    :param batch_size: 每个请求送多少条，默认取配置（并受 ``embedding_max_batch`` 限制）
    :param concurrency: 同时在途的请求数，默认取配置
    :param progress: 可选回调 ``callable(done, total)``，用于脚本打印进度
    """
    if not texts:
        return []
    if not settings.embedding_ready:
        raise EmbeddingError(
            "未配置 EMBEDDING_API_KEY（也未配置 LLM_API_KEY），无法调用云端向量化接口"
        )

    batch_size = max(
        1, min(batch_size or settings.embedding_batch, settings.embedding_max_batch)
    )
    concurrency = concurrency or settings.embedding_concurrency
    batches = [texts[i : i + batch_size] for i in range(0, len(texts), batch_size)]
    results: list[list[float] | None] = [None] * len(texts)
    semaphore = asyncio.Semaphore(max(1, concurrency))
    done = 0
    lock = asyncio.Lock()

    # 不继承 HTTP_PROXY：云端接口按需走 OUTBOUND_PROXY，本地 TEI 直连更稳
    async with build_async_client(timeout=settings.embedding_timeout) as client:

        async def run(index: int, chunk: list[str]) -> None:
            nonlocal done
            async with semaphore:
                vectors = await _post_embed(client, chunk)
                offset = index * batch_size
                for i, vec in enumerate(vectors):
                    results[offset + i] = vec
                async with lock:
                    done += len(chunk)
                    if progress and callable(progress):
                        progress(done, len(texts))

        await asyncio.gather(*(run(i, b) for i, b in enumerate(batches)))

    missing = sum(1 for r in results if r is None)
    if missing:
        raise EmbeddingError(f"有 {missing} 条文本未取到向量")
    return [r for r in results if r is not None]


async def embed_query(text: str, *, with_instruction: bool = False) -> list[float]:
    """把用户问题向量化。

    BGE 官方建议短查询加检索指令，但本库用四组法律问题实测（违约金/合同解除/
    股东知情权/人身损害赔偿），**不加指令时相似度整体更高、排序也更准**
    （如「违约金过高如何调整」top1 由第五百八十八条回到第五百八十五条，
    分数 0.579 → 0.710）。因此默认不加，``with_instruction`` 保留用于对比。

    换云端模型（如 text-embedding-v4）后同样默认不加：它的查询/文档对称性
    由模型自身处理，硬拼指令反而可能拉偏。
    """
    prepared = f"{BGE_QUERY_INSTRUCTION}{text}" if with_instruction else text
    vectors = await embed_texts([prepared[: settings.embedding_max_chars]])
    return vectors[0]


async def check_health() -> dict[str, object]:
    """探测向量服务，返回 ``{ok, provider, url, model, dim}``，失败时带 ``error``。

    云端接口没有统一的 ``/health``，用一条极短文本走真实调用探测：
    鉴权、模型名、维度、网络一次性验证完，比任何自检接口都可靠。
    """
    info: dict[str, object] = {
        "ok": False,
        "provider": settings.embedding_provider,
        "url": settings.embedding_base_url.rstrip("/"),
        "model": settings.embedding_model,
        "dim": settings.embedding_dim,
    }
    if settings.embedding_provider == "tei":
        try:
            async with build_async_client(timeout=5) as client:
                resp = await client.get(f"{info['url']}/health")
                info["ok"] = resp.status_code == 200
                if not info["ok"]:
                    info["error"] = f"健康检查返回 {resp.status_code}"
        except httpx.HTTPError as exc:
            info["error"] = f"{exc.__class__.__name__}: 无法连接 {info['url']}"
        return info

    if not settings.embedding_key:
        info["error"] = "未配置 EMBEDDING_API_KEY / LLM_API_KEY"
        return info
    try:
        async with build_async_client(timeout=10) as client:
            vectors = await _post_embed(client, ["健康检查"])
        info["ok"] = bool(vectors and len(vectors[0]) == settings.embedding_dim)
        if not info["ok"]:
            info["error"] = "返回向量维度与 EMBEDDING_DIM 不一致"
    except EmbeddingError as exc:
        info["error"] = str(exc)
    except httpx.HTTPError as exc:
        info["error"] = f"{exc.__class__.__name__}: 无法连接 {info['url']}"
    return info
