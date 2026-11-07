"""案件摘要自测脚本（任务拆解 9.6 验收用）。

覆盖四件事：

========================================  ==============================
检查项                                    对应条目
========================================  ==============================
摘要 Prompt 的六节结构与事实约束           9.6.1
SSE 全链路（meta/context/delta/done）      9.6.2
摘要完整性与材料清单                       9.6 / 9.9.3
权限与入参（客户 403、不存在 404）          9.9 / 5.8
========================================  ==============================

用法::

    cd backend

    # 只测提示词拼装（不需要后端与 Key）
    .venv/Scripts/python.exe scripts/case_summary_smoke.py --prompt

    # 走真实接口（后端已启动、Key 可用、案件 22 已有文书/合同/附件）
    .venv/Scripts/python.exe scripts/case_summary_smoke.py --summary --case-id 22

    # 全跑
    .venv/Scripts/python.exe scripts/case_summary_smoke.py --all --case-id 22
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx

from app.ai import case_prompts

DEFAULT_USER = "guyuefangyuan"
DEFAULT_PASSWORD = os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
CLIENT_USER = "bainingbing"
CLIENT_PASSWORD = os.getenv("SEED_CLIENT_PASSWORD", "bnb123456")

# 摘要必须出现的六节（与 case_prompts.SECTIONS 对应，但这里只比中文标题，
# 避免脚本和实现绑死；标题被改坏时应当被发现）
SECTION_TITLES = (
    "案件概况",
    "争议焦点",
    "事实与证据",
    "有利与不利",
    "下一步与期限",
    "材料缺口",
)


def _h(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _login(client: httpx.Client, base: str, username: str, password: str) -> dict:
    resp = client.post(
        f"{base}/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _read_sse(resp: httpx.Response) -> dict[str, list[dict]]:
    events: dict[str, list[dict]] = {}
    for block in resp.text.split("\n\n"):
        if not block.strip():
            continue
        head, _, data = block.partition("\n")
        name = head.replace("event: ", "").strip()
        payload = json.loads(data[6:]) if data.startswith("data: ") else {}
        events.setdefault(name, []).append(payload)
    return events


# ---------------------------------------------------------------------------
# 1. 提示词拼装（9.6.1）
# ---------------------------------------------------------------------------


def check_prompt() -> bool:
    _h("[1] 摘要 Prompt 结构与材料约束")
    ok = True

    messages = case_prompts.build_case_summary_messages(
        meta={
            "案号": "LF2026110005",
            "案件名称": "武家起诉乔家占福地",
            "当前阶段": "办理中",
            "标的额": "¥120,000.00",
        },
        timeline=[
            "2026-10-01｜立案｜案件立案，案号 LF2026110005",
            "2026-10-20｜开庭｜第一次开庭",
        ],
        schedules=["2026-12-01 09:00｜期限｜提交补充证据【已逾期未完成】"],
        materials=[
            {
                "kind_label": "案件文书",
                "title": "民事起诉状（民事起诉状）",
                "text": "原告武某诉称……",
                "chars": 8000,
                "truncated": True,
                "note": "仅前 6,000 字",
            }
        ],
        skipped=["《现场照片.jpg》（扫描件无文字层）"],
        focus="重点核对宅基地权属证据",
    )

    system = messages[0]["content"]
    user = messages[1]["content"]

    has_sections = all(title in system for title in SECTION_TITLES)
    ok &= has_sections
    print(f"  {'✅' if has_sections else '❌'} 系统提示词包含六个固定小节")

    has_rules = all(
        keyword in system
        for keyword in ("材料未载明", "初步判断", "待核实", "不得凭常识补全")
    )
    ok &= has_rules
    print(f"  {'✅' if has_rules else '❌'} 含「不补全 / 事实与判断分离」约束")

    has_meta = all(
        text in user for text in ("LF2026110005", "武家起诉乔家占福地", "2026-10-20")
    )
    ok &= has_meta
    print(f"  {'✅' if has_meta else '❌'} 案件字段与时间线进入用户消息")

    has_material = all(
        text in user for text in ("案件文书", "已节选", "仅前 6,000 字")
    )
    ok &= has_material
    print(f"  {'✅' if has_material else '❌'} 材料标题带「已节选」标记")

    has_gap = "未纳入本次摘要的材料" in user and "现场照片" in user
    ok &= has_gap
    print(f"  {'✅' if has_gap else '❌'} 未纳入材料单独列出（供「材料缺口」使用）")

    has_focus = "重点核对宅基地权属证据" in user
    ok &= has_focus
    print(f"  {'✅' if has_focus else '❌'} 关注点进入用户消息")

    # 没有材料时也必须明确告知"仅依据档案"，不能让模型误以为卷宗齐全
    empty = case_prompts.build_case_summary_messages(
        meta={"案号": "LF-X"},
        timeline=[],
        schedules=[],
        materials=[],
        skipped=[],
    )
    empty_user = empty[1]["content"]
    empty_ok = "没有可读取的案卷材料" in empty_user and "档案未登记时间线" in empty_user
    ok &= empty_ok
    print(f"  {'✅' if empty_ok else '❌'} 空材料/空时间线有明确说明")

    return bool(ok)


# ---------------------------------------------------------------------------
# 2. SSE 全链路（9.6.2）
# ---------------------------------------------------------------------------


def check_summary(client: httpx.Client, base: str, case_id: int) -> bool:
    _h(f"[2] SSE 全链路 + 摘要完整性（case={case_id}）")
    headers = {
        **_login(client, base, DEFAULT_USER, DEFAULT_PASSWORD),
        "Accept": "text/event-stream",
    }
    started = time.perf_counter()
    resp = client.post(
        f"{base}/ai/case-summary/{case_id}",
        headers=headers,
        json={"focus": "重点核对时间线与证据缺口"},
        timeout=600,
    )
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}：{resp.text[:300]}")
        return False

    events = _read_sse(resp)
    elapsed = time.perf_counter() - started
    ok = True
    print(f"  事件：{ {k: len(v) for k, v in events.items()} } | {elapsed:.1f}s")

    for name in ("meta", "context", "stage", "done"):
        has = name in events
        ok &= has
        print(f"  {'✅' if has else '❌'} 收到 {name} 事件")

    if "error" in events:
        print(f"  ❌ error：{events['error'][0].get('detail')}")
        return False

    meta = events["meta"][0]
    context = events["context"][0]
    done = events["done"][0]
    content = done.get("content") or ""

    print(
        f"  材料：{meta.get('material_count')} 份 / "
        f"{meta.get('material_chars')} 字 | 截断={meta.get('truncated')} | "
        f"文书 {context.get('counts', {}).get('documents')} / "
        f"附件 {context.get('counts', {}).get('attachments')} / "
        f"合同 {context.get('counts', {}).get('contracts')}"
    )
    print(f"  材料清单：{[m['title'] for m in context.get('materials', [])][:6]}")

    long_enough = len(content) >= 400
    ok &= long_enough
    print(f"  {'✅' if long_enough else '❌'} 摘要长度 {len(content)} 字（≥400）")

    missing = [title for title in SECTION_TITLES if title not in content]
    sections_ok = not missing
    ok &= sections_ok
    print(f"  {'✅' if sections_ok else '❌'} 六节齐全" + (f"，缺：{missing}" if missing else ""))

    html = done.get("html") or ""
    html_ok = html.startswith("<") and "<h2" in html
    ok &= html_ok
    print(f"  {'✅' if html_ok else '❌'} done.html 已渲染为 HTML")

    if meta.get("material_count", 0) > 0:
        has_materials = len(context.get("materials") or []) > 0
        ok &= has_materials
        print(f"  {'✅' if has_materials else '❌'} 材料清单非空（含文书/合同/附件）")

    # 历史读取：刷新页面后应能回填同一份摘要
    resp = client.get(
        f"{base}/ai/case-summary/{case_id}",
        headers=_login(client, base, DEFAULT_USER, DEFAULT_PASSWORD),
    )
    latest = resp.json() if resp.status_code == 200 else {}
    history_ok = (
        resp.status_code == 200
        and latest.get("content") == content
        and bool(latest.get("html"))
    )
    ok &= history_ok
    print(f"  {'✅' if history_ok else '❌'} GET 最近摘要与本次一致")

    print("\n  ---- 摘要前 900 字 ----")
    print(content[:900].replace("\n", "\n  "))
    return bool(ok)


# ---------------------------------------------------------------------------
# 3. 权限与入参
# ---------------------------------------------------------------------------


def check_guard(client: httpx.Client, base: str, case_id: int) -> bool:
    _h("[3] 权限与入参校验")
    ok = True
    staff = _login(client, base, DEFAULT_USER, DEFAULT_PASSWORD)

    # 3.1 客户账号不能生成摘要
    client_h = _login(client, base, CLIENT_USER, CLIENT_PASSWORD)
    resp = client.post(
        f"{base}/ai/case-summary/{case_id}",
        headers={**client_h, "Accept": "text/event-stream"},
        timeout=60,
    )
    denied = resp.status_code == 403
    ok &= denied
    print(f"  {'✅' if denied else '❌'} 客户账号生成摘要 → {resp.status_code}（期望 403）")

    # 3.2 客户账号也不能读取历史摘要
    resp = client.get(f"{base}/ai/case-summary/{case_id}", headers=client_h)
    denied = resp.status_code == 403
    ok &= denied
    print(f"  {'✅' if denied else '❌'} 客户账号读取摘要 → {resp.status_code}（期望 403）")

    # 3.3 不存在的案件
    resp = client.post(
        f"{base}/ai/case-summary/999999",
        headers={**staff, "Accept": "text/event-stream"},
        timeout=60,
    )
    not_found = resp.status_code == 404
    ok &= not_found
    print(f"  {'✅' if not_found else '❌'} 不存在的案件 → {resp.status_code}（期望 404）")

    # 3.4 关注点超长（>300 字）应被 pydantic 拒绝
    resp = client.post(
        f"{base}/ai/case-summary/{case_id}",
        headers={**staff, "Accept": "text/event-stream"},
        json={"focus": "太长" * 200},
        timeout=60,
    )
    rejected = resp.status_code == 422
    ok &= rejected
    print(f"  {'✅' if rejected else '❌'} 关注点超长 → {resp.status_code}（期望 422）")

    return bool(ok)


def main() -> int:
    parser = argparse.ArgumentParser(description="9.6 案件摘要自测")
    parser.add_argument("--base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--case-id", type=int, default=22)
    parser.add_argument("--prompt", action="store_true", help="只测提示词拼装")
    parser.add_argument("--summary", action="store_true", help="测 SSE 全链路")
    parser.add_argument("--guard", action="store_true", help="测权限与入参")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not any((args.prompt, args.summary, args.guard, args.all)):
        args.all = True

    results: list[bool] = []
    if args.prompt or args.all:
        results.append(check_prompt())

    if args.summary or args.guard or args.all:
        with httpx.Client(timeout=600, trust_env=False) as client:
            if args.summary or args.all:
                results.append(check_summary(client, args.base, args.case_id))
            if args.guard or args.all:
                results.append(check_guard(client, args.base, args.case_id))

    passed = sum(1 for item in results if item)
    print(f"\n{'=' * 60}\n结果：{passed}/{len(results)} 项通过\n{'=' * 60}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
