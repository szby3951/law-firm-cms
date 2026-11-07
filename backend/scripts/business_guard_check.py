"""双入口边界核查：会话隔离、类型过滤、权限、入参守卫。

用法::

    cd backend
    .venv/Scripts/python.exe scripts/business_guard_check.py

全部为断言式检查，任一项失败即打印 FAIL 并以非零码退出。
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

BASE = os.environ.get("API_BASE", "http://127.0.0.1:8000")
FAILED: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  [{'OK  ' if ok else 'FAIL'}] {name}{(' — ' + detail) if detail else ''}")
    if not ok:
        FAILED.append(name)


async def login(client: httpx.AsyncClient, username: str, password: str) -> str:
    resp = await client.post(
        f"{BASE}/api/auth/login", json={"username": username, "password": password}
    )
    if resp.status_code != 200:
        raise SystemExit(f"登录失败 {resp.status_code}: {resp.text[:200]}")
    return resp.json()["access_token"]


async def ask(client, token: str, path: str, question: str) -> tuple[int, int | None]:
    """返回 (HTTP 状态码, 会话 id)。非 200 时 id 为 None。"""
    async with client.stream(
        "POST",
        f"{BASE}{path}",
        json={"question": question},
        headers={"Authorization": f"Bearer {token}"},
        timeout=120,
    ) as resp:
        if resp.status_code != 200:
            await resp.aread()
            return resp.status_code, None
        session_id = None
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            try:
                data = json.loads(line[6:])
            except json.JSONDecodeError:
                continue
            if data.get("type") == "meta" and data.get("session_id"):
                session_id = int(data["session_id"])
        return 200, session_id


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="guyuefangyuan")
    parser.add_argument(
        "--password", default=os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
    )
    parser.add_argument("--base", default="", help="接口根地址，默认取 API_BASE 或 8000")
    args = parser.parse_args()

    global BASE
    if args.base:
        BASE = args.base.rstrip("/")

    async with httpx.AsyncClient(trust_env=False) as client:
        token = await login(client, args.username, args.password)
        auth = {"Authorization": f"Bearer {token}"}

        print("\n## 1. 两个入口各自建会话")
        code, biz_id = await ask(client, token, "/api/business/chat", "我还差多少钱？")
        check("business 入口 200 且返回会话 id", code == 200 and biz_id is not None, f"id={biz_id}")
        code, law_id = await ask(client, token, "/api/ai/chat", "违约金过高如何调整")
        check("law 入口 200 且返回会话 id", code == 200 and law_id is not None, f"id={law_id}")

        print("\n## 2. 会话不能跨入口续接")
        code, _ = await ask(
            client, token, "/api/ai/chat", "接着上面那个问题继续"
        )  # 不传 id，正常建新会话
        check("law 不传 session_id 可新建", code == 200)

        # 用业务会话 id 调法律问答
        async with client.stream(
            "POST",
            f"{BASE}/api/ai/chat",
            json={"question": "继续", "session_id": biz_id},
            headers=auth,
            timeout=60,
        ) as resp:
            await resp.aread()
            check("业务会话不能续接到 law", resp.status_code == 404, f"HTTP {resp.status_code}")

        # 用法律会话 id 调业务问答
        async with client.stream(
            "POST",
            f"{BASE}/api/business/chat",
            json={"question": "继续", "session_id": law_id},
            headers=auth,
            timeout=60,
        ) as resp:
            await resp.aread()
            check("法律会话不能续接到 business", resp.status_code == 404, f"HTTP {resp.status_code}")

        print("\n## 3. 会话列表按类型过滤")
        r = await client.get(f"{BASE}/api/ai/sessions", params={"type": "business"}, headers=auth)
        items = r.json().get("items", [])
        check("type=business 只返回业务会话", all(i["type"] == "business" for i in items), f"{len(items)} 条")
        r = await client.get(f"{BASE}/api/ai/sessions", params={"type": "chat"}, headers=auth)
        items = r.json().get("items", [])
        check("type=chat 只返回问答会话", all(i["type"] == "chat" for i in items), f"{len(items)} 条")
        r = await client.get(f"{BASE}/api/ai/sessions", headers=auth)
        types = {i["type"] for i in r.json().get("items", [])}
        check("不传 type 返回全部类型", len(types) >= 1, f"类型={sorted(types)}")

        print("\n## 4. 会话详情按类型给不同声明")
        r = await client.get(f"{BASE}/api/ai/sessions/{biz_id}", headers=auth)
        data = r.json()
        check(
            "业务会话详情用数据口径声明",
            "以案件与账单页面登记为准" in (data.get("disclaimer") or ""),
            data.get("disclaimer"),
        )
        r = await client.get(f"{BASE}/api/ai/sessions/{law_id}", headers=auth)
        data = r.json()
        check(
            "法律会话详情用法律免责声明",
            "不构成法律意见" in (data.get("disclaimer") or ""),
            data.get("disclaimer"),
        )

        print("\n## 5. 详情接口不能跨入口打开")
        r = await client.get(
            f"{BASE}/api/ai/sessions/{biz_id}", params={"type": "chat"}, headers=auth
        )
        check("督办会话用 chat 打开返回 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = await client.get(
            f"{BASE}/api/ai/sessions/{law_id}", params={"type": "business"}, headers=auth
        )
        check("法律会话用 business 打开返回 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = await client.get(
            f"{BASE}/api/ai/sessions/{biz_id}", params={"type": "business"}, headers=auth
        )
        msgs = (r.json().get("messages") or []) if r.status_code == 200 else []
        check("督办会话用 business 打开正常", bool(msgs), f"HTTP {r.status_code} 消息 {len(msgs)} 条")
        r = await client.get(
            f"{BASE}/api/ai/sessions/{law_id}", params={"type": "chat"}, headers=auth
        )
        msgs = (r.json().get("messages") or []) if r.status_code == 200 else []
        check("法律会话用 chat 打开正常", bool(msgs), f"HTTP {r.status_code} 消息 {len(msgs)} 条")

        print("\n## 6. 入参守卫")
        r = await client.post(f"{BASE}/api/business/chat", json={"question": "a"}, headers=auth)
        check("问题过短被拒（422）", r.status_code == 422, f"HTTP {r.status_code}")
        r = await client.post(
            f"{BASE}/api/business/chat", json={"question": "x" * 600}, headers=auth
        )
        check("问题超长被拒（422）", r.status_code == 422, f"HTTP {r.status_code}")
        r = await client.post(
            f"{BASE}/api/business/chat",
            json={"question": "我还差多少钱", "top_k": 6},
            headers=auth,
        )
        check("业务入口无 top_k 字段也不报错（忽略多余字段）", r.status_code == 200, f"HTTP {r.status_code}")
        if r.status_code == 200:
            await r.aread()

        print("\n## 7. 权限：客户只能看自己")
        ct = await login(client, "bainingbing", "bnb123456")
        async with client.stream(
            "POST",
            f"{BASE}/api/business/chat",
            json={"question": "我的案件办到哪了？"},
            headers={"Authorization": f"Bearer {ct}"},
            timeout=120,
        ) as resp:
            cas = []
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    try:
                        d = json.loads(line[6:])
                    except json.JSONDecodeError:
                        continue
                    if d.get("type") == "context":
                        cas.append(len(d.get("items") or []))
            check("客户入口 200 并有业务数据", resp.status_code == 200 and cas, f"条目={cas}")

        # 客户端的两个页面各取一类会话，这里验证服务端确实只返回该类型，
        # 否则客户会在法律问答的历史里看到督办记录
        cauth = {"Authorization": f"Bearer {ct}"}
        r = await client.get(
            f"{BASE}/api/ai/sessions", params={"type": "chat"}, headers=cauth
        )
        items = r.json().get("items", [])
        check(
            "客户 chat 列表不含督办会话",
            all(i["type"] == "chat" for i in items),
            f"{len(items)} 条",
        )
        r = await client.get(
            f"{BASE}/api/ai/sessions", params={"type": "business"}, headers=cauth
        )
        items = r.json().get("items", [])
        check(
            "客户 business 列表不含问答会话",
            all(i["type"] == "business" for i in items),
            f"{len(items)} 条",
        )

        print("\n## 8. 删除会话（客户端的删除按钮走这个接口）")
        r = await client.get(f"{BASE}/api/ai/sessions/{biz_id}", headers=auth)
        before = r.json().get("message_count") if r.status_code == 200 else None
        r = await client.delete(f"{BASE}/api/ai/sessions/{biz_id}", headers=auth)
        check("删除自己的督办会话返回 204", r.status_code == 204, f"HTTP {r.status_code}")
        r = await client.get(f"{BASE}/api/ai/sessions/{biz_id}", headers=auth)
        check("删除后详情返回 404", r.status_code == 404, f"HTTP {r.status_code}")
        r = await client.get(
            f"{BASE}/api/ai/sessions", params={"type": "business"}, headers=auth
        )
        ids = [i["id"] for i in r.json().get("items", [])]
        check("删除后不再出现在列表", biz_id not in ids, f"原 {before} 条消息，剩余会话 {len(ids)} 个")

        r = await client.delete(
            f"{BASE}/api/ai/sessions/{law_id}",
            headers={"Authorization": f"Bearer {ct}"},
        )
        check("客户不能删律师的会话", r.status_code in (403, 404), f"HTTP {r.status_code}")

    print()
    if FAILED:
        print(f"FAILED {len(FAILED)} 项：{FAILED}")
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(main())
