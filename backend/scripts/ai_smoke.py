"""AIGateway 自测脚本（任务拆解 9.2 验收用）。

只验证「模型接入层」，不涉及 RAG/业务接口：流式是否真的逐段到达、JSON 是否能
解析、换配置是否生效、出错是否降级成友好提示。

用法::

    cd backend

    # 1) 查看当前配置（不含 Key）
    .venv/Scripts/python.exe scripts/ai_smoke.py --config

    # 2) 探活
    .venv/Scripts/python.exe scripts/ai_smoke.py --health

    # 3) 真实调用（需在 .env 配好 LLM_API_KEY）
    .venv/Scripts/python.exe scripts/ai_smoke.py --all --question "违约金过高如何调整"

    # 4) 无 Key 的离线验证：先起 mock，再把地址指过去
    .venv/Scripts/python.exe scripts/mock_llm_server.py
    LLM_BASE_URL=http://127.0.0.1:8099/v1 LLM_API_KEY=test-key \
        .venv/Scripts/python.exe scripts/ai_smoke.py --all
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ai.gateway import LLMError, get_gateway


def _print_config(gw) -> None:
    info = gw.describe()
    print("当前配置（已隐藏 Key）：")
    for key, value in info.items():
        print(f"  {key:14s}= {value}")
    print(f"  api_key_configured= {bool(gw.enabled)}")


async def _health(gw) -> bool:
    data = await gw.health()
    llm, vec = data["llm"], data["embedding"]
    print(
        f"大模型 : {'✅' if llm.get('ok') else '❌'} {llm.get('provider')}/{llm.get('model')}"
    )
    if llm.get("error"):
        print(f"         原因：{llm['error']}")
    if llm.get("models"):
        print(f"         可用模型：{', '.join(str(m) for m in llm['models'][:5])}")
    print(
        f"向量服务: {'✅' if vec.get('ok') else '❌'} {vec.get('url')} ({vec.get('dim')} 维)"
    )
    if vec.get("error"):
        print(f"         原因：{vec['error']}")
    print(
        f"整体    : {'可用' if data['ok'] else '不可用（AI 功能降级，主系统不受影响）'}"
    )
    return bool(data["ok"])


async def _chat(gw, question: str, fallback: str | bool | None) -> None:
    print(f"\n[流式对话] {question}")
    started = time.perf_counter()
    first_at: float | None = None
    pieces: list[str] = []
    async for piece in gw.chat(
        question,
        system="你是律所的法律助手，回答简洁准确。",
        fallback=fallback,
    ):
        if first_at is None:
            first_at = time.perf_counter() - started
        pieces.append(piece)
        print(piece, end="", flush=True)
    total = time.perf_counter() - started
    text = "".join(pieces)
    print()
    print(
        f"  首段延迟 {first_at * 1000:.0f} ms | 总耗时 {total * 1000:.0f} ms | "
        f"分段 {len(pieces)} 个 | {len(text)} 字"
    )
    if len(pieces) <= 1 and len(text) > 20:
        print("  ⚠️ 只收到 1 段，可能是非流式返回或未解析出 SSE 分片")


async def _json(gw) -> None:
    print("\n[结构化输出] 请模型输出审查报告 JSON")
    started = time.perf_counter()
    data = await gw.generate_json(
        "请审查这句话的合同风险：本合同自签署之日起生效，任何一方不得解除。",
        schema_hint='{"level": "high|mid|low", "risks": [{"clause": "条款", "advice": "建议"}]}',
        system="你是合同审查助手，只输出 JSON。",
    )
    elapsed = time.perf_counter() - started
    import json as _json

    print(
        f"  解析成功，{len(_json.dumps(data, ensure_ascii=False))} 字节，耗时 {elapsed * 1000:.0f} ms"
    )
    print("  " + _json.dumps(data, ensure_ascii=False)[:300])


async def _embed(gw, text: str) -> None:
    print(f"\n[向量化] {text}")
    started = time.perf_counter()
    vectors = await gw.embed([text])
    elapsed = time.perf_counter() - started
    vec = vectors[0]
    print(
        f"  维度 {len(vec)} | 模长 {sum(v * v for v in vec) ** 0.5:.4f} | 耗时 {elapsed:.2f} s"
    )


async def _run(args) -> int:
    gw = get_gateway()
    if args.config:
        _print_config(gw)
    if args.health:
        await _health(gw)
        return 0

    try:
        if args.all or args.chat:
            await _chat(gw, args.question, fallback=None if args.strict else True)
        if args.all or args.json:
            await _json(gw)
        if args.all or args.embed:
            await _embed(gw, args.question)
    except LLMError as exc:
        print(f"\n❌ 调用失败：{exc}")
        print(f"   面向用户的降级文案：{exc.friendly}")
        print(f"   可重试：{exc.retryable} | 上游状态码：{exc.status_code}")
        return 2
    except Exception as exc:  # noqa: BLE001 - 自测脚本，需要看到真实异常类型
        print(f"\n❌ 非预期异常：{type(exc).__name__}: {exc}")
        return 3
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="AIGateway 接入层自测")
    parser.add_argument(
        "--config", action="store_true", help="打印当前配置（不含 Key）"
    )
    parser.add_argument("--health", action="store_true", help="只探活")
    parser.add_argument("--chat", action="store_true", help="流式对话")
    parser.add_argument("--json", action="store_true", help="结构化 JSON 输出")
    parser.add_argument("--embed", action="store_true", help="向量化")
    parser.add_argument("--all", action="store_true", help="依次执行 chat/json/embed")
    parser.add_argument(
        "--strict", action="store_true", help="失败时抛异常，不使用降级文案"
    )
    parser.add_argument(
        "--question",
        default="当事人约定的违约金过分高于实际损失，可以请求调整吗？",
        help="对话与向量化使用的问题",
    )
    args = parser.parse_args()
    if not any([args.config, args.health, args.chat, args.json, args.embed, args.all]):
        parser.print_help()
        return 1
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
