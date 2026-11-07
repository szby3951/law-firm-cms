"""客户画像自测脚本（任务拆解 9.7 验收用）。

覆盖四件事：

========================================  ==============================
检查项                                    对应条目
========================================  ==============================
画像 Prompt 的字段结构与 JSON 容错          9.7.3
生成全链路（聚合 → 脱敏 → JSON → 写回）      9.7.2 / 9.7.4 / 9.7.5
画像可读回、可刷新                          9.7.5
权限与入参（客户 403、不存在 404）            9.7.5 / 5.8
========================================  ==============================

用法::

    cd backend

    # 只测提示词与 JSON 规范化（不需要后端与 Key）
    .venv/Scripts/python.exe scripts/profile_smoke.py --prompt

    # 走真实接口（后端已启动、Key 可用、客户 67 有跟进/案件/合同/留言/收费）
    .venv/Scripts/python.exe scripts/profile_smoke.py --profile --client-id 67

    # 全跑
    .venv/Scripts/python.exe scripts/profile_smoke.py --all --client-id 67
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

from app.ai import profile_prompts

DEFAULT_USER = "guyuefangyuan"
DEFAULT_PASSWORD = os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
CLIENT_USER = "bainingbing"
CLIENT_PASSWORD = os.getenv("SEED_CLIENT_PASSWORD", "bnb123456")

# 任务拆解 9.7.3 模板里的五个必填字段
TEMPLATE_FIELDS = ("客户类型", "核心诉求", "风险点", "沟通偏好", "下一步跟进建议")
# 为落地使用补充的三个字段
EXTRA_FIELDS = ("标签", "数据依据", "数据缺口")


def _h(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _login(client: httpx.Client, base: str, username: str, password: str) -> dict:
    resp = client.post(
        f"{base}/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


# ---------------------------------------------------------------------------
# 1. 提示词与 JSON 规范化（9.7.3）
# ---------------------------------------------------------------------------


def check_prompt() -> bool:
    _h("[1] 画像 Prompt 结构 + JSON 容错")
    ok = True

    messages = profile_prompts.build_profile_messages(
        meta={
            "客户名称": "武*",
            "客户类型": "个人",
            "来源渠道": "门店",
            "漏斗状态": "潜在（尚未成交）",
            "客户分级": "VIP",
            "联系电话": "166****2014",
        },
        follows=["2026-11-03 19:55｜面访｜古月方源｜提出主要诉求，希望尽快办理"],
        cases=["LF2026110005｜土地纠纷｜已立案｜标的 ¥10,000,000.00"],
        contracts=["武*土地委派合同｜¥30,000.00｜生效中｜AI 审查发现 8 处风险"],
        billing=["LF2026110005｜应收 ¥30,000.00｜已收 ¥10,800.00｜未收 ¥19,200.00"],
        messages=["2026-11-04｜客户：下周开庭需要准备哪些材料？"],
        skipped=["共有 20 条跟进，仅纳入最近 8 条"],
        focus="重点判断回款风险",
    )

    system = messages[0]["content"]
    user = messages[1]["content"]

    has_fields = all(field in system for field in TEMPLATE_FIELDS + EXTRA_FIELDS)
    ok &= has_fields
    print(f"  {'✅' if has_fields else '❌'} 系统提示词含五项模板字段与三个辅助字段")

    has_rules = all(
        keyword in system
        for keyword in ("数据不足", "不要凭常识补全", "严禁还原", "最多 3 条")
    )
    ok &= has_rules
    print(f"  {'✅' if has_rules else '❌'} 含「不推测 / 不还原脱敏 / 风险≤3」约束")

    has_material = all(
        text in user
        for text in ("【跟进记录】", "【关联案件】", "【合同】", "【收费与回款】", "【沟通记录】")
    )
    ok &= has_material
    print(f"  {'✅' if has_material else '❌'} 六类数据分节进入用户消息")

    has_meta = all(text in user for text in ("武*", "166****2014", "门店"))
    ok &= has_meta
    print(f"  {'✅' if has_meta else '❌'} 脱敏后的客户档案进入用户消息")

    has_gap = "共有 20 条跟进" in user and "重点判断回款风险" in user
    ok &= has_gap
    print(f"  {'✅' if has_gap else '❌'} 未纳入说明与关注点进入用户消息")

    # 空数据也必须明确告知，不能让模型以为「没有记录 = 没有风险」
    empty = profile_prompts.build_profile_messages(
        meta={"客户名称": "某*"},
        follows=[],
        cases=[],
        contracts=[],
        billing=[],
        messages=[],
        skipped=[],
    )
    empty_user = empty[1]["content"]
    empty_ok = (
        "无跟进记录" in empty_user
        and "无关联案件" in empty_user
        and "无收费方案" in empty_user
    )
    ok &= empty_ok
    print(f"  {'✅' if empty_ok else '❌'} 空数据有明确说明（避免被当成无风险）")

    # ---- JSON 容错：代码围栏 + 中英混用 + 字符串风险点 + 超过 3 条 ----
    raw = """```json
{"client_type": "贸易商，决策快", "core_demands": "尽快回款",
 "风险点": ["预期过高", {"风险": "付款拖延", "依据": "首期逾期 20 天", "应对": "约谈财务"},
            "沟通失联", "第四条应被截断"],
 "沟通偏好": "微信，晚间",
 "下一步跟进建议": "1. 三天内电话\\n2. 下周面谈",
 "标签": "价格敏感;决策链短", "数据依据": ["跟进 10-01"], "数据缺口": []}
```"""
    profile = profile_prompts.normalize_profile(profile_prompts.parse_json_object(raw))
    truncated = len(profile["risks"]) == 3
    ok &= truncated
    print(f"  {'✅' if truncated else '❌'} 风险点截断为 3 条（实际 {len(profile['risks'])}）")

    shaped = (
        profile["client_type"] == "贸易商，决策快"
        and profile["risks"][1]["basis"] == "首期逾期 20 天"
        and profile["tags"] == ["价格敏感", "决策链短"]
        and "\n" in profile["next_actions"]
    )
    ok &= shaped
    print(f"  {'✅' if shaped else '❌'} 中英键映射、风险结构、标签拆分、编号换行正常")

    rejected = False
    try:
        profile_prompts.normalize_profile({"风险点": ["只有风险"]})
    except profile_prompts.ProfileFormatError:
        rejected = True
    ok &= rejected
    print(f"  {'✅' if rejected else '❌'} 缺「客户类型/核心诉求」时判为无效（不写库）")

    return bool(ok)


# ---------------------------------------------------------------------------
# 2. 生成全链路（9.7.2 ~ 9.7.5）
# ---------------------------------------------------------------------------


def check_profile(client: httpx.Client, base: str, client_id: int) -> bool:
    _h(f"[2] 生成全链路 + 画像质量（client={client_id}）")
    headers = _login(client, base, DEFAULT_USER, DEFAULT_PASSWORD)
    ok = True

    detail = client.get(f"{base}/clients/{client_id}", headers=headers)
    if detail.status_code != 200:
        print(f"  ❌ 读取客户失败：HTTP {detail.status_code}")
        return False
    real_name = detail.json().get("name") or ""

    started = time.perf_counter()
    resp = client.post(
        f"{base}/clients/{client_id}/ai-profile",
        headers=headers,
        json={"focus": "重点判断回款风险与流失可能"},
        timeout=300,
    )
    elapsed = time.perf_counter() - started
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}：{resp.text[:300]}")
        return False

    data = resp.json()
    profile = data.get("profile") or {}
    inputs = data.get("inputs") or {}
    stats = inputs.get("stats") or {}
    masked = inputs.get("masked") or {}
    print(
        f"  客户：{real_name} | 用时 {elapsed:.1f}s | {data.get('model')} | "
        f"纳入 {inputs.get('counts', {}).get('included')} 条记录"
    )
    print(f"  读取范围：{json.dumps(stats, ensure_ascii=False)}")

    type_ok = bool(profile.get("client_type")) and bool(profile.get("core_demands"))
    ok &= type_ok
    print(f"  {'✅' if type_ok else '❌'} 客户类型与核心诉求非空")

    risks_ok = isinstance(profile.get("risks"), list) and len(profile["risks"]) <= 3
    ok &= risks_ok
    print(f"  {'✅' if risks_ok else '❌'} 风险点不超过 3 条（{len(profile.get('risks') or [])}）")

    tags_ok = 1 <= len(profile.get("tags") or []) <= 6
    ok &= tags_ok
    print(f"  {'✅' if tags_ok else '❌'} 标签数量 1~6（{profile.get('tags')}）")

    actions_ok = len(profile.get("next_actions") or "") >= 30
    ok &= actions_ok
    print(f"  {'✅' if actions_ok else '❌'} 跟进建议具体可执行（{len(profile.get('next_actions') or '')} 字）")

    evidence_ok = bool(profile.get("evidence"))
    ok &= evidence_ok
    print(f"  {'✅' if evidence_ok else '❌'} 给出数据依据 {len(profile.get('evidence') or [])} 条")

    stats_ok = all(key in stats for key in ("follows", "cases", "messages", "due_total"))
    ok &= stats_ok
    print(f"  {'✅' if stats_ok else '❌'} 返回读取范围统计（跟进/案件/留言/应收）")

    masked_ok = bool(masked.get("summary"))
    ok &= masked_ok
    print(f"  {'✅' if masked_ok else '❌'} 脱敏命中：{masked.get('summary') or '无'}")

    # 脱敏后模型不应知道客户真名；输出里出现完整姓名说明有漏点
    body = json.dumps(profile, ensure_ascii=False)
    leak = bool(real_name) and len(real_name) >= 2 and real_name in body
    ok &= not leak
    print(f"  {'✅' if not leak else '❌'} 画像未出现客户真名（脱敏有效）")

    # 读回：刷新页面应回填同一份，时间/标签一致
    resp = client.get(f"{base}/clients/{client_id}/ai-profile", headers=headers)
    saved = resp.json() if resp.status_code == 200 else {}
    history_ok = (
        resp.status_code == 200
        and saved.get("profile", {}).get("client_type") == profile.get("client_type")
        and saved.get("ai_profile_at") == data.get("ai_profile_at")
    )
    ok &= history_ok
    print(f"  {'✅' if history_ok else '❌'} GET 回填与本次一致")

    print("\n  ---- 画像摘录 ----")
    print(f"  客户类型：{profile.get('client_type')}")
    print(f"  核心诉求：{(profile.get('core_demands') or '')[:160]}")
    print(f"  标签：{'、'.join(profile.get('tags') or [])}")
    for index, risk in enumerate(profile.get("risks") or [], 1):
        print(f"  风险{index}：{risk.get('point')}")
        if risk.get("basis"):
            print(f"          依据：{risk['basis'][:100]}")
    return bool(ok)


# ---------------------------------------------------------------------------
# 3. 权限与入参
# ---------------------------------------------------------------------------


def check_guard(client: httpx.Client, base: str, client_id: int) -> bool:
    _h("[3] 权限与入参校验")
    ok = True
    staff = _login(client, base, DEFAULT_USER, DEFAULT_PASSWORD)

    client_h = _login(client, base, CLIENT_USER, CLIENT_PASSWORD)
    resp = client.post(
        f"{base}/clients/{client_id}/ai-profile", headers=client_h, json={}
    )
    denied = resp.status_code == 403
    ok &= denied
    print(f"  {'✅' if denied else '❌'} 客户账号生成画像 → {resp.status_code}（期望 403）")

    resp = client.get(f"{base}/clients/{client_id}/ai-profile", headers=client_h)
    denied = resp.status_code == 403
    ok &= denied
    print(f"  {'✅' if denied else '❌'} 客户账号读取画像 → {resp.status_code}（期望 403）")

    resp = client.get(f"{base}/clients/999999/ai-profile", headers=staff)
    not_found = resp.status_code == 404
    ok &= not_found
    print(f"  {'✅' if not_found else '❌'} 不存在的客户 → {resp.status_code}（期望 404）")

    resp = client.post(
        f"{base}/clients/{client_id}/ai-profile",
        headers=staff,
        json={"focus": "太长" * 200},
    )
    rejected = resp.status_code == 422
    ok &= rejected
    print(f"  {'✅' if rejected else '❌'} 关注点超长 → {resp.status_code}（期望 422）")

    return bool(ok)


def main() -> int:
    parser = argparse.ArgumentParser(description="9.7 客户画像自测")
    parser.add_argument("--base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--client-id", type=int, default=67)
    parser.add_argument("--prompt", action="store_true", help="只测提示词与 JSON 容错")
    parser.add_argument("--profile", action="store_true", help="测生成全链路")
    parser.add_argument("--guard", action="store_true", help="测权限与入参")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not any((args.prompt, args.profile, args.guard, args.all)):
        args.all = True

    results: list[bool] = []
    if args.prompt or args.all:
        results.append(check_prompt())

    if args.profile or args.guard or args.all:
        with httpx.Client(timeout=300, trust_env=False) as client:
            if args.profile or args.all:
                results.append(check_profile(client, args.base, args.client_id))
            if args.guard or args.all:
                results.append(check_guard(client, args.base, args.client_id))

    passed = sum(1 for item in results if item)
    print(f"\n{'=' * 60}\n结果：{passed}/{len(results)} 项通过\n{'=' * 60}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
