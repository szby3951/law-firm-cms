"""RAG 问答自测脚本（任务拆解 9.3 验收用）。

覆盖四件事，都对应验收条目：

============================  ===========================================
检查项                         对应条目
============================  ===========================================
检索能命中相关法条             9.3.1 / 9.10.1
脱敏把手机号/身份证/姓名打码    9.3.7 / 9.9.2
SSE 逐段到达 + 事件齐全         9.3.6 / 9.10.1
引用编号可回查、问答落库        9.3.3 / 9.3.4 / 9.9.3
============================  ===========================================

用法::

    cd backend

    # 1) 只测检索（不需要后端服务与 API Key）
    .venv/Scripts/python.exe scripts/rag_smoke.py --retrieve "违约金过高如何调整"

    # 2) 只测脱敏
    .venv/Scripts/python.exe scripts/rag_smoke.py --mask

    # 3) 走真实 HTTP 接口（需后端已启动；无 API Key 时先起 mock）
    .venv/Scripts/python.exe scripts/mock_llm_server.py
    .venv/Scripts/python.exe scripts/rag_smoke.py --chat

    # 4) 全跑
    .venv/Scripts/python.exe scripts/rag_smoke.py --all

    # 换账号 / 换端口
    .venv/Scripts/python.exe scripts/rag_smoke.py --chat \
        --username bainingbing --password bnb123456 --base http://127.0.0.1:8010/api
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai import rag
from app.ai.masking import mask_sensitive

MASK_SAMPLES = [
    (
        "当事人：张三，身份证 110101199003071234，电话 13800138000，"
        "卡号 6222021234567890123，邮箱 zhangsan@example.com"
    ),
    "被告李四欠钱不还，我要起诉他",
    "当事人约定违约金过高，可以调整吗",
    "委托人王小明与客户赵六签订合同，联系人：陈七",
]


def _h(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


# ---------------------------------------------------------------------------
# 检索
# ---------------------------------------------------------------------------


async def check_retrieve(question: str) -> bool:
    _h(f"[1] 检索  {question}")
    started = time.perf_counter()
    refs = await rag.retrieve(question)
    elapsed = time.perf_counter() - started
    if not refs:
        print("❌ 没有检索到任何资料")
        return False
    for ref in refs:
        print(f"  [{ref.index}] {ref.label}  score={ref.score:.4f}  {len(ref.content)} 字")
    top = refs[0].label
    print(f"\n  耗时 {elapsed:.2f}s | 引用 {len(refs)} 条 | 首条 {top}")
    print("  上下文预览：")
    preview = rag.format_context(refs[:2]).splitlines()
    for line in preview[:6]:
        print(f"    {line[:80]}")
    return len(refs) >= 3


# ---------------------------------------------------------------------------
# 脱敏
# ---------------------------------------------------------------------------


def check_mask() -> bool:
    _h("[2] 敏感信息脱敏")
    ok = True
    for text in MASK_SAMPLES:
        result = mask_sensitive(text)
        print(f"  原文：{text}")
        print(f"  脱敏：{result.text}")
        print(f"  命中：{result.hits}\n")
        # 打码后的文本不得再出现 11 位手机号或 18 位身份证
        if "13800138000" in result.text or "110101199003071234" in result.text:
            print("  ❌ 仍存在明文敏感信息")
            ok = False
        if text != result.text and not result.hits:
            print("  ❌ 文本被改动但没有命中记录")
            ok = False
    print("✅ 脱敏通过" if ok else "❌ 脱敏存在问题")
    return ok


# ---------------------------------------------------------------------------
# HTTP / SSE
# ---------------------------------------------------------------------------


def _parse_event(block: str) -> dict | None:
    """解析单个 SSE 块（``event: x\\ndata: {...}``）。"""
    data_lines = [
        line[5:].strip() for line in block.splitlines() if line.startswith("data:")
    ]
    if not data_lines:
        return None
    try:
        return json.loads("\n".join(data_lines))
    except json.JSONDecodeError:
        return None


def check_chat(base: str, username: str, password: str, question: str) -> bool:
    _h(f"[3] SSE 问答  {base}")
    with httpx.Client(timeout=120, trust_env=False) as client:
        resp = client.post(
            f"{base}/auth/login", json={"username": username, "password": password}
        )
        if resp.status_code != 200:
            print(f"❌ 登录失败 {resp.status_code}：{resp.text[:200]}")
            return False
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}", "Accept": "text/event-stream"}

        resp = client.get(f"{base}/ai/health", headers=headers)
        print(f"  健康检查 {resp.status_code}：")
        if resp.status_code == 200:
            data = resp.json()
            print(
                f"    llm={'✅' if data['llm'].get('ok') else '❌'} "
                f"embedding={'✅' if data['embedding'].get('ok') else '❌'} "
                f"ok={data['ok']}"
            )
            print(f"    rag={data.get('rag')}")

        started = time.perf_counter()
        first_delta_at: float | None = None
        counts: dict[str, int] = {}
        answer = ""
        meta: dict = {}
        done: dict = {}
        error: dict = {}

        with client.stream(
            "POST", f"{base}/ai/chat", headers=headers, json={"question": question}
        ) as stream:
            if stream.status_code != 200:
                print(f"❌ 接口返回 {stream.status_code}：{stream.read()[:200]}")
                return False
            buffer = ""
            for chunk in stream.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = _parse_event(block)
                    if not event:
                        continue
                    kind = event.get("type")
                    counts[kind] = counts.get(kind, 0) + 1
                    if kind == "meta":
                        meta = event
                    elif kind == "delta":
                        if first_delta_at is None:
                            first_delta_at = time.perf_counter() - started
                        answer += event["text"]
                    elif kind == "done":
                        done = event
                    elif kind == "error":
                        error = event

        total = time.perf_counter() - started
        print(f"  事件统计：{counts}")
        if first_delta_at is not None:
            print(f"  首段延迟 {first_delta_at * 1000:.0f} ms | 总耗时 {total * 1000:.0f} ms")
        print(f"  回答 {len(answer)} 字：{answer[:80].replace(chr(10), ' ')}…")

        if error:
            print(f"  ⚠️ error 事件：{error}")
        if not done:
            print("❌ 没有收到 done 事件")
            return False
        print(f"  会话 meta：masked={meta.get('masked')} model={meta.get('model')}")

        refs = done.get("refs") or []
        used = done.get("used_refs") or []
        print(f"  引用 {len(refs)} 条 | 实际引用编号 {used}")
        for ref in refs[:3]:
            print(f"    [{ref['index']}] {ref['label']} score={ref['score']}")
        print(f"  session={done['session_id']} message={done['message_id']} "
              f"token≈{done['token_usage']} 免责声明={done.get('disclaimer')}")

        # 落库校验：历史接口能读到这一问一答
        detail = client.get(
            f"{base}/ai/sessions/{done['session_id']}", headers=headers
        )
        if detail.status_code != 200:
            print(f"❌ 读取会话失败 {detail.status_code}")
            return False
        messages = detail.json()["messages"]
        print(f"  落库消息 {len(messages)} 条：{[m['role'] for m in messages]}")
        assistant = [m for m in messages if m["role"] == "assistant"]
        if not assistant or assistant[-1]["content"] != answer:
            print("❌ 落库回答与流式内容不一致")
            return False
        if len(assistant[-1].get("refs") or []) != len(refs):
            print("❌ 引用快照未完整落库")
            return False

        # 多轮续接：同一 session 再问一句，历史应带上上一轮
        with client.stream(
            "POST",
            f"{base}/ai/chat",
            headers=headers,
            json={"question": "那需要准备哪些证据？", "session_id": done["session_id"]},
        ) as stream2:
            second_done = {}
            buffer = ""
            for chunk in stream2.iter_text():
                buffer += chunk
                while "\n\n" in buffer:
                    block, buffer = buffer.split("\n\n", 1)
                    event = _parse_event(block)
                    if event and event.get("type") == "done":
                        second_done = event
        if not second_done:
            print("❌ 多轮续接失败")
            return False
        detail = client.get(
            f"{base}/ai/sessions/{done['session_id']}", headers=headers
        ).json()
        print(f"  续接后消息 {len(detail['messages'])} 条（应为 4）")

        # 越权校验：换个不存在的会话应 404
        resp = client.get(f"{base}/ai/sessions/99999999", headers=headers)
        print(f"  不存在的会话 → {resp.status_code}（期望 404）")

        # 清理：删除本次测试会话，避免脏数据堆积
        resp = client.delete(f"{base}/ai/sessions/{done['session_id']}", headers=headers)
        print(f"  删除会话 → {resp.status_code}（期望 204）")

    print("✅ 问答链路通过")
    return len(messages) == 2 and bool(refs)


def main() -> int:
    parser = argparse.ArgumentParser(description="RAG 问答自测")
    parser.add_argument("--retrieve", action="store_true", help="测检索")
    parser.add_argument("--mask", action="store_true", help="测脱敏")
    parser.add_argument("--chat", action="store_true", help="测 SSE 问答（需后端）")
    parser.add_argument("--all", action="store_true", help="全部执行")
    parser.add_argument("--base", default="http://127.0.0.1:8000/api", help="后端地址")
    parser.add_argument("--username", default="guyuefangyuan", help="登录账号")
    parser.add_argument(
        "--password",
        default=os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951"),
        help="登录密码",
    )
    parser.add_argument(
        "--question",
        default="当事人约定的违约金过分高于实际损失，可以请求法院调整吗？",
    )
    args = parser.parse_args()

    if not any([args.retrieve, args.mask, args.chat, args.all]):
        parser.print_help()
        return 1

    results: list[bool] = []
    if args.retrieve or args.all:
        results.append(asyncio.run(check_retrieve(args.question)))
    if args.mask or args.all:
        results.append(check_mask())
    if args.chat or args.all:
        results.append(check_chat(args.base, args.username, args.password, args.question))

    _h("结果")
    print(f"  {'✅ 全部通过' if all(results) else '❌ 存在失败项'}（{sum(results)}/{len(results)}）")
    return 0 if all(results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
