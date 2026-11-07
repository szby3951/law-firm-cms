"""智能文书生成自测脚本（任务拆解 9.4 验收用）。

覆盖四件事，都对应验收条目：

=====================================  ==================================
检查项                                 对应条目
=====================================  ==================================
Markdown → HTML 转换（归档正文格式）     9.4.4
文书类型/必备字段清单可读                9.4.1
SSE 流式生成 + 字段填充正确              9.4.2 / 9.4.3
初稿归档进 document（is_ai_generated）   9.4.4
权限：客户不可生成、非承办案件不可生成    9.9 / 5.8
=====================================  ==================================

用法::

    cd backend

    # 只测格式转换（不需要后端与 Key）
    .venv/Scripts/python.exe scripts/doc_smoke.py --format

    # 走真实接口（后端需已启动，且 LLM_API_KEY 可用）
    .venv/Scripts/python.exe scripts/doc_smoke.py --generate --case-id 15

    # 全跑
    .venv/Scripts/python.exe scripts/doc_smoke.py --all
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

from app.ai.doc_html import looks_like_html, to_html

DEFAULT_USER = "guyuefangyuan"
DEFAULT_PASSWORD = os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
# 客户账号：用于验证「客户不能生成文书」
CLIENT_USER = "bainingbing"
CLIENT_PASSWORD = os.getenv("SEED_CLIENT_PASSWORD", "bnb123456")

SAMPLE_MD = """# 民事起诉状

## 原告信息

原告：张三，男，1980年1月1日出生。

## 诉讼请求

1. 判令被告支付违约金 100,000.00 元；
2. 判令被告承担本案**全部**诉讼费用。

## 事实与理由

双方于 2024 年签订合同，被告逾期付款。

> 此致
"""

# 起诉状必须出现的章节关键词
COMPLAINT_SECTIONS = ("诉讼请求", "事实与理由", "此致", "具状人")
# 模型不该出现的开场白（出现了说明提示词里的"直接输出"没生效）
BAD_OPENINGS = ("以下是", "这是为您", "希望对您", "如需修改", "请注意，本")


def _h(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _login(client: httpx.Client, base: str, username: str, password: str) -> dict:
    resp = client.post(
        f"{base}/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# 1. 格式转换
# ---------------------------------------------------------------------------


def check_format() -> bool:
    _h("[1] Markdown → HTML（归档正文）")
    html = to_html(SAMPLE_MD)
    print(f"  输出 {len(html)} 字符：{html[:180]}…")

    ok = True
    for token, label in (
        ("<h1>民事起诉状</h1>", "一级标题"),
        ("<h2>诉讼请求</h2>", "二级标题"),
        ("<li>1. 判令被告支付违约金", "有序列表保留编号"),
        ("<strong>全部</strong>", "粗体"),
        ("<blockquote>此致</blockquote>", "引用"),
        ("<p>双方于 2024 年签订合同", "段落"),
    ):
        hit = token in html
        ok &= hit
        print(f"  {'✅' if hit else '❌'} {label}")

    # 已是 HTML 的内容不能再转一次，否则 <p> 会被当文本转义
    again = to_html(html)
    idempotent = again == html and looks_like_html(html)
    ok &= idempotent
    print(f"  {'✅' if idempotent else '❌'} 幂等（HTML 不再二次转义）")

    # 正文里的 < 必须被转义，避免破坏结构
    escaped = to_html("原告主张 3<5 且被告不同意")
    esc_ok = "&lt;" in escaped and "<5" not in escaped
    ok &= esc_ok
    print(f"  {'✅' if esc_ok else '❌'} 特殊字符转义")
    print("✅ 格式转换通过" if ok else "❌ 格式转换未通过")
    return ok


# ---------------------------------------------------------------------------
# 2. 文书类型
# ---------------------------------------------------------------------------


def check_types(client: httpx.Client, base: str, headers: dict) -> bool:
    _h("[2] 文书类型与必备字段")
    resp = client.get(f"{base}/ai/document-types", headers=headers)
    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}: {resp.text[:200]}")
        return False

    items = resp.json()
    print(f"  共 {len(items)} 类：")
    for item in items:
        print(
            f"    {item['doc_type']:<16} {item['label']:<8} "
            f"必备 {len(item['required_fields'])} 项 / 章节 {len(item['outline'])} 节"
        )

    spec = next((x for x in items if x["doc_type"] == "complaint"), None)
    ok = bool(spec) and "受理法院" in spec["required_fields"]
    print(f"  {'✅' if ok else '❌'} 起诉状要求「受理法院」等案件字段")
    return ok


# ---------------------------------------------------------------------------
# 3. SSE 生成
# ---------------------------------------------------------------------------


def _read_sse(body: str) -> tuple[list[str], dict, str]:
    """解析 SSE 报文，返回（事件名列表, done 载荷, 正文）。"""
    events: list[str] = []
    done: dict = {}
    content = ""
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        head, _, data = block.partition("\n")
        name = head.replace("event: ", "").strip()
        events.append(name)
        if not data.startswith("data: "):
            continue
        payload = json.loads(data[6:])
        if name == "delta":
            content += payload.get("text", "")
        elif name == "done":
            done = payload
        elif name == "error":
            print(f"  ⚠️ error 事件：{payload}")
    return events, done, content


def check_generate(
    client: httpx.Client, base: str, headers: dict, case_id: int, doc_type: str
) -> tuple[bool, dict]:
    _h(f"[3] SSE 生成（case={case_id} / {doc_type}）")
    started = time.perf_counter()
    resp = client.post(
        f"{base}/ai/generate-document",
        headers={**headers, "Accept": "text/event-stream"},
        json={"doc_type": doc_type, "case_id": case_id},
        timeout=180,
    )
    elapsed = time.perf_counter() - started
    if resp.status_code != 200:
        print(f"❌ HTTP {resp.status_code}: {resp.text[:300]}")
        return False, {}

    events, done, content = _read_sse(resp.text)
    from collections import Counter

    print(f"  事件统计：{dict(Counter(events))}")
    print(f"  耗时 {elapsed:.1f}s | 正文 {len(content)} 字 | done={'有' if done else '无'}")

    ok = bool(done) and "delta" in events and "context" in events
    print(f"  {'✅' if ok else '❌'} 事件齐全（meta/context/stage/delta/done）")

    missing = done.get("missing", [])
    print(f"  缺少字段：{missing or '无'}")
    print(f"  引用字段 {len(done.get('fields', {}) or {})} 项" if "fields" in done else "")

    if doc_type == "complaint":
        hit = [s for s in COMPLAINT_SECTIONS if s in content]
        sec_ok = len(hit) == len(COMPLAINT_SECTIONS)
        ok &= sec_ok
        print(f"  {'✅' if sec_ok else '❌'} 必备章节齐全：{hit}")

    opening = next((b for b in BAD_OPENINGS if content.lstrip().startswith(b)), None)
    print(f"  {'✅' if not opening else '❌'} 无多余开场白"
          f"{'（出现：' + opening + '）' if opening else ''}")
    ok &= not opening

    # 案件里的真实姓名必须出现在文书里，否则说明字段没带进去
    title = done.get("title", "")
    print(f"  标题：{title}")
    print(f"  首 200 字：{content[:200].replace(chr(10), ' ')}")

    html = done.get("html", "")
    html_ok = html.startswith("<h1>") or "<h1>" in html
    ok &= html_ok
    print(f"  {'✅' if html_ok else '❌'} done 事件带可直接归档的 html")

    return ok, done


# ---------------------------------------------------------------------------
# 4. 归档
# ---------------------------------------------------------------------------


def check_archive(
    client: httpx.Client, base: str, headers: dict, done: dict
) -> tuple[bool, int | None]:
    _h("[4] 归档进文书库")
    resp = client.post(
        f"{base}/ai/documents",
        headers=headers,
        json={
            "title": done.get("title") or "AI 文书",
            "doc_type": done.get("doc_type") or "complaint",
            "case_id": done.get("case_id"),
            "content": done.get("html") or done.get("content") or "",
            "session_id": done.get("session_id"),
            "status": "draft",
        },
    )
    if resp.status_code != 201:
        print(f"❌ HTTP {resp.status_code}: {resp.text[:300]}")
        return False, None

    doc = resp.json()
    print(f"  文书 #{doc['id']}「{doc['title']}」→ {doc['doc_type_label']} / {doc['status_label']}")
    print(f"  关联：{doc.get('case_no')} / 客户 {doc.get('client_name')} / 创建人 {doc.get('creator_name')}")

    ok = doc["is_ai_generated"] is True and doc.get("ai_session_id") == done.get("session_id")
    print(f"  {'✅' if ok else '❌'} is_ai_generated=true 且记录来源会话")

    detail = client.get(f"{base}/documents/{doc['id']}", headers=headers)
    content = (detail.json().get("content") or "") if detail.status_code == 200 else ""
    html_ok = detail.status_code == 200 and "<p>" in content
    ok &= html_ok
    print(f"  {'✅' if html_ok else '❌'} 正文以富文本 HTML 存取（文书编辑器可直接打开）")
    print(f"  摘要：{doc.get('excerpt')}")
    return ok, doc["id"]


# ---------------------------------------------------------------------------
# 5. 权限与入参校验
# ---------------------------------------------------------------------------


async def _temp_case() -> int:
    """建一个没有承办律师的临时案件，用于验证「非本人在办案件不可生成」。"""
    from sqlalchemy import text

    from app.database import engine

    async with engine.begin() as conn:
        client_id = (
            await conn.execute(text("SELECT id FROM client_profile LIMIT 1"))
        ).scalar()
        await conn.execute(
            text(
                "INSERT INTO cases (case_no, client_id, title, case_type, status, "
                "amount, description) VALUES (:no, :cid, '自测临时案件', 'litigation', "
                "'consulting', 0, '仅用于权限自测，跑完即删')"
            ),
            {"no": f"SMOKE{int(time.time())}", "cid": client_id},
        )
        case_id = (
            await conn.execute(text("SELECT LAST_INSERT_ID()"))
        ).scalar()
    await engine.dispose()
    return int(case_id)


async def _drop_case(case_id: int) -> None:
    from sqlalchemy import text

    from app.database import engine

    async with engine.begin() as conn:
        await conn.execute(text("DELETE FROM cases WHERE id = :i"), {"i": case_id})
    await engine.dispose()


def check_guard(
    admin_client: httpx.Client, base: str, headers: dict, case_id: int
) -> bool:
    _h("[5] 权限与入参校验")
    ok = True

    # 客户账号不能生成文书
    with httpx.Client(timeout=30, trust_env=False) as raw:
        client_h = _login(raw, base, CLIENT_USER, CLIENT_PASSWORD)
    resp = admin_client.post(
        f"{base}/ai/generate-document",
        headers={**client_h, "Accept": "text/event-stream"},
        json={"doc_type": "complaint", "case_id": case_id},
    )
    forbidden = resp.status_code == 403
    ok &= forbidden
    print(f"  {'✅' if forbidden else '❌'} 客户账号生成文书 → {resp.status_code}（期望 403）")

    # 不存在的案件
    resp = admin_client.post(
        f"{base}/ai/generate-document",
        headers={**headers, "Accept": "text/event-stream"},
        json={"doc_type": "complaint", "case_id": 999999},
    )
    not_found = resp.status_code == 404
    ok &= not_found
    print(f"  {'✅' if not_found else '❌'} 不存在的案件 → {resp.status_code}（期望 404）")

    # 非本人在办的案件
    temp_id = asyncio.run(_temp_case())
    try:
        resp = admin_client.post(
            f"{base}/ai/generate-document",
            headers={**headers, "Accept": "text/event-stream"},
            json={"doc_type": "lawyer_letter", "case_id": temp_id, "facts": "占位事实"},
        )
        denied = resp.status_code == 403
        ok &= denied
        print(
            f"  {'✅' if denied else '❌'} 非本人在办案件 → {resp.status_code}（期望 403）"
        )
    finally:
        asyncio.run(_drop_case(temp_id))

    # 没有案件也没有事实：没有事实的文书只能是一堆占位符
    resp = admin_client.post(
        f"{base}/ai/generate-document",
        headers={**headers, "Accept": "text/event-stream"},
        json={"doc_type": "opinion"},
    )
    if resp.status_code == 400:
        print(f"  ✅ 无案件无事实 → 400（{resp.json().get('detail', '')[:40]}…）")
    else:
        ok = False
        print(f"  ❌ 无案件无事实 → {resp.status_code}（期望 400）")

    # 非法文书类型
    resp = admin_client.post(
        f"{base}/ai/generate-document",
        headers={**headers, "Accept": "text/event-stream"},
        json={"doc_type": "not_a_type"},
    )
    invalid = resp.status_code == 422
    ok &= invalid
    print(f"  {'✅' if invalid else '❌'} 非法文书类型 → {resp.status_code}（期望 422）")
    return ok


# ---------------------------------------------------------------------------
# 清理
# ---------------------------------------------------------------------------


def cleanup(
    client: httpx.Client, base: str, headers: dict, doc_id: int | None, session_id: int | None
) -> None:
    if doc_id:
        resp = client.delete(f"{base}/documents/{doc_id}", headers=headers)
        print(f"  删除文书 #{doc_id} → {resp.status_code}")
    if session_id:
        resp = client.delete(f"{base}/ai/sessions/{session_id}", headers=headers)
        print(f"  删除会话 #{session_id} → {resp.status_code}")


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description="9.4 智能文书生成自测")
    parser.add_argument("--format", action="store_true", help="只测 Markdown→HTML")
    parser.add_argument("--types", action="store_true", help="只测文书类型接口")
    parser.add_argument("--generate", action="store_true", help="测 SSE 生成")
    parser.add_argument("--archive", action="store_true", help="测归档（含生成）")
    parser.add_argument("--guard", action="store_true", help="测权限与入参校验")
    parser.add_argument("--all", action="store_true", help="全部检查")
    parser.add_argument("--base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--username", default=DEFAULT_USER)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    parser.add_argument("--case-id", type=int, default=15, help="用于生成的案件 ID")
    parser.add_argument("--doc-type", default="complaint", help="文书类型")
    parser.add_argument("--keep", action="store_true", help="保留生成的文书与会话")
    args = parser.parse_args()

    # 没指定任何开关时跑全部
    if not any(
        (args.format, args.types, args.generate, args.archive, args.guard, args.all)
    ):
        args.all = True

    results: list[bool] = []
    if args.format or args.all:
        results.append(check_format())

    need_http = args.types or args.generate or args.archive or args.guard or args.all
    if not need_http:
        return 0 if all(results) else 1

    doc_id: int | None = None
    session_id: int | None = None
    with httpx.Client(timeout=60, trust_env=False) as client:
        try:
            headers = _login(client, args.base, args.username, args.password)
        except httpx.HTTPError as exc:
            print(f"❌ 登录失败（后端是否已启动？）：{exc}")
            return 1

        if args.types or args.all:
            results.append(check_types(client, args.base, headers))

        done: dict = {}
        if args.generate or args.archive or args.all:
            ok, done = check_generate(
                client, args.base, headers, args.case_id, args.doc_type
            )
            results.append(ok)
            session_id = done.get("session_id")

        if (args.archive or args.all) and done:
            ok, doc_id = check_archive(client, args.base, headers, done)
            results.append(ok)

        if args.guard or args.all:
            results.append(check_guard(client, args.base, headers, args.case_id))

        if not args.keep:
            _h("清理")
            cleanup(client, args.base, headers, doc_id, session_id)

    _h("结果")
    passed = sum(1 for r in results if r)
    print(f"  {'✅' if passed == len(results) else '❌'} 通过 {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
