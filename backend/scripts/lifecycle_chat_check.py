"""双入口核查：法律问答与「AI督办」是否各管各的。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/lifecycle_chat_check.py              # 两个入口都测
    .venv/Scripts/python.exe scripts/lifecycle_chat_check.py --mode business
    .venv/Scripts/python.exe scripts/lifecycle_chat_check.py --as-user-id 6   # 客户视角

判断标准（脚本会打印，人工看）：

- ``law`` 入口：只出现法条与制度，出现 ``[n]`` 引用，**不应**逐条罗列本人的案件
  与金额，也不该说"我查不到你的案件"——那属于业务入口。
- ``business`` 入口：只出现台账数字，**不应**出现 ``[n]`` 编号与法条分析，
  没有 ``refs`` 事件。

脚本只读：登录 → 发问 → 打印 SSE 事件与回答全文，不写业务数据
（``ai_session`` / ``ai_message`` 里会留一条记录，与真实使用一致）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

BASE = "http://127.0.0.1:8000"

LAW_QUESTIONS = [
    "违约金约定过高，法院一般如何调整？",
    "我手上案件办到哪一步了，帮我看一下",  # 故意问错入口，验证不再答"查不到"
]

BUSINESS_QUESTIONS = [
    "我手上这个案子办理到哪一步了？下一步要做什么？",
    "我这个案子的律师费是多少？已经付了多少钱、还差多少？",
    "违约金过高的话，法院一般怎么调整？",  # 故意问法律问题，验证不越界
]


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        f"{BASE}/api/auth/login", json={"username": username, "password": password}
    )
    if resp.status_code != 200:
        raise SystemExit(f"登录失败 {resp.status_code}: {resp.text[:200]}")
    return resp.json()["access_token"]


async def mint_token(user_id: int) -> str:
    """按用户 id 直接签发令牌，用于不知道密码的种子客户账号（只读，不改密码）。"""
    from app.core.security import create_access_token
    from app.database import SessionLocal
    from app.models.user import User

    async with SessionLocal() as db:
        user = await db.get(User, user_id)
        if user is None:
            raise SystemExit(f"用户 {user_id} 不存在")
        print(f"以用户身份 {user.username}（{user.role}）签发临时令牌")
        return create_access_token(user.id, user.role)


async def ask(
    client: httpx.AsyncClient, token: str, question: str, *, mode: str
) -> dict:
    events: list[str] = []
    deltas: list[str] = []
    refs: list[dict] = []
    context: dict = {}
    path = "/api/ai/chat" if mode == "law" else "/api/business/chat"
    body = {"question": question}

    async with client.stream(
        "POST",
        f"{BASE}{path}",
        json=body,
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    ) as resp:
        if resp.status_code != 200:
            text = (await resp.aread()).decode("utf-8", "ignore")
            print(f"  ! HTTP {resp.status_code}: {text[:300]}")
            return {}
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            kind = data.get("type") or data.get("event")
            events.append(str(kind))
            if kind == "delta":
                deltas.append(data.get("text", ""))
            elif kind == "refs":
                refs = data.get("items") or []
            elif kind == "context":
                context = data
                print(
                    f"  [context] 角色={data.get('scope')} "
                    f"截至={data.get('as_of')} 条目={len(data.get('items') or [])} "
                    f"字数={data.get('chars')} 裁剪={data.get('truncated')}"
                )
                for item in (data.get("items") or [])[:6]:
                    print(
                        f"      - {item.get('kind'):8s} {item.get('label')}"
                        f"｜{item.get('detail')}｜{item.get('link')}"
                    )
            elif kind == "warning":
                print(f"  ! warning: {data.get('detail')}")
            elif kind == "error":
                print(f"  ! error: {data.get('detail')}")

    answer = "".join(deltas)
    print(f"  事件序列: {' → '.join(dict.fromkeys(events))}（共 {len(events)} 段）")
    print(f"  引用: {len(refs)} 条")
    print(f"  回答({len(answer)} 字):")
    for line in answer.splitlines():
        if line.strip():
            print(f"    {line}")
    return {"answer": answer, "refs": refs, "events": events, "context": context}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="guyuefangyuan")
    parser.add_argument(
        "--password", default=os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
    )
    parser.add_argument(
        "--mode",
        choices=["law", "business", "both"],
        default="both",
        help="测哪个入口",
    )
    parser.add_argument("--questions", nargs="*", default=None, help="覆盖默认问题")
    parser.add_argument(
        "--as-user-id", type=int, default=None, help="按用户 id 签发令牌（免密码）"
    )
    args = parser.parse_args()

    async with httpx.AsyncClient(trust_env=False) as client:
        if args.as_user_id:
            token = await mint_token(args.as_user_id)
        else:
            token = await login(client, args.username, args.password)
            print(f"登录成功：{args.username}\n")

        modes = ["law", "business"] if args.mode == "both" else [args.mode]
        for mode in modes:
            questions = args.questions or (
                LAW_QUESTIONS if mode == "law" else BUSINESS_QUESTIONS
            )
            title = "AI 法律问答" if mode == "law" else "AI督办"
            print("=" * 70)
            print(f"## {title}（{mode}）")
            print("=" * 70)
            for q in questions:
                print(f"\n【问】{q}")
                await ask(client, token, q, mode=mode)
            print()


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
