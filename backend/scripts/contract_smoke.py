"""合同风险审查自测脚本（任务拆解 9.5 验收用）。

覆盖五件事：

========================================  ==================================
检查项                                    对应条目
========================================  ==================================
文本抽取 / 条款切分 / 要素定位 / 分批       9.5.1
风险清单与提示词拼装                       9.5.2
结构化输出解析容错（中文键、裸数组、等级）   9.5.3
SSE 全链路 + 写回 contract.ai_review_report 9.5.4
权限与入参（客户 403、无文件 400、越权 403） 9.9 / 5.8
========================================  ==================================

用法::

    cd backend

    # 只测切分与解析（不需要后端与 Key）
    .venv/Scripts/python.exe scripts/contract_smoke.py --digest

    # 走真实接口（后端已启动、Key 可用、合同 8 已上传 docx）
    .venv/Scripts/python.exe scripts/contract_smoke.py --review

    # 全跑
    .venv/Scripts/python.exe scripts/contract_smoke.py --all --contract-id 8
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

from app.ai import contract_prompts as cp
from app.ai import contract_text as ct

DEFAULT_USER = "guyuefangyuan"
DEFAULT_PASSWORD = os.getenv("SEED_LAWYER_PASSWORD", "gyfy3951")
CLIENT_USER = "bainingbing"
CLIENT_PASSWORD = os.getenv("SEED_CLIENT_PASSWORD", "bnb123456")

# 合成一份「多章节 + 有空白 + 缺管辖」的长合同，用于验证分批与规则预检
LONG_CONTRACT = """设备采购与技术服务合同

甲方（采购方）：某某科技有限公司
乙方（供应方）：某某设备制造有限公司

第1章 总则

第一条 合同标的
乙方向甲方提供型号为 XX-2000 的生产线设备一套，并负责安装、调试与培训。
设备清单、技术参数见附件一，附件一为本合同不可分割的组成部分。

第二条 合同金额
本合同总价款为人民币 1,200,000 元（大写：壹佰贰拾万元整），含税。
价款包含设备款、运输费、安装调试费与培训费，不含甲方现场改造费用。

第三条 付款方式
合同签订后 5 个工作日内，甲方支付合同总价的 30% 作为预付款。
设备到货验收合格后支付 60%，质保期满支付剩余 10%。
乙方应在收款前开具 13% 增值税专用发票，逾期开票甲方有权顺延付款。

第四条 交付与验收
乙方应于 2026 年 6 月 30 日前完成交付。
甲方应在设备到场后【 】日内完成验收，验收标准见附件二。
验收不合格的，乙方应在 15 日内整改并重新提交验收。

第2章 权利与义务

第五条 甲方权利义务
甲方应按约定支付价款，并提供设备安装所需的场地、电力与网络条件。
甲方有权对设备质量进行监督检查，有权要求乙方更换不符合约定的部件。

第六条 乙方权利义务
乙方应按约定的时间、质量标准交付设备，并提供不少于 2 年的免费质保。
乙方应指派专职工程师负责安装调试，未经甲方书面同意不得分包。
乙方应保证设备不侵犯任何第三方的知识产权。

第七条 保密
双方对履行本合同知悉的对方商业秘密负有保密义务，保密期限为合同终止后 3 年。
违反保密义务的一方应赔偿对方因此遭受的全部损失。

第3章 违约责任与其他

第八条 违约责任
甲方逾期付款的，每逾期一日按逾期金额的 0.5% 向乙方支付违约金，上不封顶。
乙方逾期交付的，每逾期一日按合同总价的 0.1% 支付违约金。
因一方违约造成对方损失的，还应赔偿全部直接损失与间接损失。

第九条 不可抗力
因不可抗力导致不能履行合同的，遭遇方应及时通知对方并提供证明，可部分或全部免除责任。
不可抗力包括但不限于自然灾害、战争、政府行为、市场价格剧烈波动、汇率变化。

第十条 合同变更
本合同的任何变更均需双方书面协商一致，口头变更无效。

第十一条 其他
本合同自双方签字盖章之日起生效，一式两份，双方各执一份。
未尽事宜，双方另行协商解决。
"""


def _h(title: str) -> None:
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def _login(client: httpx.Client, base: str, username: str, password: str) -> dict:
    resp = client.post(
        f"{base}/auth/login", json={"username": username, "password": password}
    )
    resp.raise_for_status()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _read_sse(resp: httpx.Response) -> dict:
    """把 SSE 响应拆成 {事件名: [payload...]}。"""
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
# 1. 切分与预检（9.5.1）
# ---------------------------------------------------------------------------


def check_digest() -> bool:
    _h("[1] 文本切分 / 要素定位 / 分批")
    ok = True

    digest = ct.digest_contract(LONG_CONTRACT)
    print(f"  条款数 {digest.clause_count} | 字数 {digest.char_count}")
    for clause in digest.clauses[:3]:
        print(f"    {clause.no}. {clause.title[:28]}（{len(clause.body)} 字）")

    expect_articles = 11
    articles = [c for c in digest.clauses if c.title.startswith("第") and "条" in c.title[:6]]
    got = len(articles)
    ok &= got == expect_articles
    print(f"  {'✅' if got == expect_articles else '❌'} 切出 {got} 条（期望 {expect_articles}）")

    # 章节归属：第一至四条应在「第1章」
    first = next((c for c in digest.clauses if "第一条" in c.title), None)
    has_section = bool(first and first.section and "总则" in first.section)
    ok &= has_section
    print(f"  {'✅' if has_section else '❌'} 条款带章节归属：{first.section if first else '-'}")

    # 要素定位：金额、违约、期限都应命中
    for name in ("金额与费用", "违约责任", "期限与生效"):
        hit = bool(digest.elements.get(name))
        ok &= hit
        print(f"  {'✅' if hit else '❌'} 定位「{name}」→ 第{digest.elements.get(name)}条")

    # 缺管辖：这份合同确实没写争议解决
    missing_ok = "争议解决" in digest.missing
    ok &= missing_ok
    print(f"  {'✅' if missing_ok else '❌'} 未命中争议解决 → missing={digest.missing}")

    # 空白项：第四条验收天数留空
    ph_ok = digest.placeholder_count >= 1 and any(
        item["clause_no"] for item in digest.placeholders
    )
    ok &= ph_ok
    print(f"  {'✅' if ph_ok else '❌'} 空白项 {digest.placeholder_count} 处")

    # 分批：6000 字上限下这份合同应至少切 1 批；把上限调小验证多批与合并
    batches, cut = ct.split_batches(
        digest.clauses, max_chars=600, max_batches=8
    )
    multi = len(batches) >= 1 and all(b for b in batches)
    ok &= multi
    covered = [c.no for batch in batches for c in batch]
    no_gap = covered == sorted(set(covered))
    ok &= no_gap
    print(
        f"  {'✅' if multi and no_gap else '❌'} 600 字上限切成 {len(batches)} 批，"
        f"条款号连续={no_gap}，截断={cut}"
    )

    # 超上限的场景
    _, truncated = ct.split_batches(digest.clauses, max_chars=600, max_batches=2)
    ok &= truncated
    print(f"  {'✅' if truncated else '❌'} 批次上限 2 时标记为截断")

    # 定位能力
    clause_no, located = digest.locate("每逾期一日按逾期金额的 0.5% 向乙方支付违约金")
    ok &= located and clause_no is not None
    print(f"  {'✅' if located else '❌'} 原文定位到第 {clause_no} 条")
    _, fake_located = digest.locate("这段文字在合同里并不存在，纯属编造")
    ok &= not fake_located
    print(f"  {'✅' if not fake_located else '❌'} 编造的原文不会被误判为已定位")
    return ok


# ---------------------------------------------------------------------------
# 2. 解析容错（9.5.3）
# ---------------------------------------------------------------------------


def check_parse() -> bool:
    _h("[2] 结构化输出解析容错")
    ok = True
    digest = ct.digest_contract(LONG_CONTRACT)

    # 2.1 裸数组 + 中文键名 + 中文等级（设计文档给的正是这种写法）
    raw_list = [
        {
            "风险条款": "违约金比例过高",
            "原文定位": "每逾期一日按逾期金额的 0.5% 向乙方支付违约金，上不封顶",
            "风险等级": "高",
            "修改建议": "调整为日万分之五并设置总额上限",
            "依据": "《民法典》第五百八十五条",
        }
    ]
    risks = cp.normalize_report(raw_list, digest)
    single_ok = (
        len(risks) == 1
        and risks[0]["level"] == "high"
        and risks[0]["located"]
        and risks[0]["clause_no"] is not None
    )
    ok &= single_ok
    print(
        f"  {'✅' if single_ok else '❌'} 裸数组/中文键名 → level={risks[0]['level'] if risks else '-'}"
        f", 定位第 {risks[0]['clause_no'] if risks else '-'} 条"
    )

    # 2.2 dict 包裹 + 越界条号 + 编造原文
    raw_dict = {
        "summary": "整体偏高",
        "risks": [
            {
                "clause": "第 99 条",
                "quote": "这句话并不在合同里",
                "risk": "编造条款",
                "level": "HIGH",
            },
            {
                "quote": "本合同自双方签字盖章之日起生效",
                "risk": "生效条件表述不清",
                "level": "低",
                "suggestion": "补充签署日期",
            },
        ],
        "missing": ["争议解决条款"],
        "notes": "建议补充附件清单",
    }
    parsed = cp.normalize_report(raw_dict, digest)
    fake = next((r for r in parsed if r["risk"] == "编造条款"), None)
    guard_ok = fake is not None and not fake["located"]
    ok &= guard_ok
    print(f"  {'✅' if guard_ok else '❌'} 编造原文标记 located=False（不伪造成原文）")
    missing_ok = cp.extract_missing(raw_dict) == ["争议解决条款"]
    ok &= missing_ok
    print(f"  {'✅' if missing_ok else '❌'} missing 解析：{cp.extract_missing(raw_dict)}")

    # 2.3 等级别名
    cases = {"高": "high", "HIGH": "high", "严重": "high", "中": "mid", "low": "low", "": "mid"}
    bad = {k: cp.normalize_level(k) for k, v in cases.items() if cp.normalize_level(k) != v}
    ok &= not bad
    print(f"  {'✅' if not bad else '❌'} 等级归一（含空值兜底）")

    # 2.4 完全无法解析的输入不应抛异常
    empty_ok = cp.normalize_report("这不是 JSON", digest) == []
    ok &= empty_ok
    print(f"  {'✅' if empty_ok else '❌'} 非 JSON 输入返回空列表而非异常")

    # 2.5 规则预检：缺争议解决应报高风险
    pre = cp.precheck_risks(digest)
    juris = next((r for r in pre if r["check"] == "jurisdiction"), None)
    pre_ok = juris is not None and juris["level"] == "high"
    ok &= pre_ok
    print(f"  {'✅' if pre_ok else '❌'} 规则预检发现缺失争议解决（{juris['level'] if juris else '-'}）")

    # 2.6 合并去重
    merged = cp.merge_risks(
        [{"clause_no": 8, "quote": "违约金", "risk": "x", "level": "low", "source": "ai"}],
        [{"clause_no": 8, "quote": "违约金", "risk": "y", "level": "high", "source": "ai"}],
    )
    merge_ok = len(merged) == 1 and merged[0]["level"] == "high"
    ok &= merge_ok
    print(f"  {'✅' if merge_ok else '❌'} 同条款同原文去重并保留更高等级")
    return ok


# ---------------------------------------------------------------------------
# 3. 全链路（9.5.4）
# ---------------------------------------------------------------------------


def check_review(client: httpx.Client, base: str, contract_id: int) -> bool:
    _h("[3] SSE 全链路 + 写回合同台账")
    headers = {**_login(client, base, DEFAULT_USER, DEFAULT_PASSWORD), "Accept": "text/event-stream"}
    started = time.perf_counter()
    resp = client.post(
        f"{base}/ai/review-contract/{contract_id}", headers=headers, timeout=600
    )
    if resp.status_code != 200:
        print(f"  ❌ HTTP {resp.status_code}：{resp.text[:200]}")
        return False
    events = _read_sse(resp)
    elapsed = time.perf_counter() - started
    ok = True

    print(f"  事件：{ {k: len(v) for k, v in events.items()} } | {elapsed:.1f}s")
    for name in ("meta", "precheck", "stage", "done"):
        has = name in events
        ok &= has
        print(f"  {'✅' if has else '❌'} 收到 {name} 事件")

    if "error" in events:
        print(f"  ❌ error：{events['error'][0].get('detail')}")
        return False

    done = events["done"][0]
    report = done["report"]
    print(f"  报告：{report['level_label']}风险 | {report['counts']} | saved={done['saved']}")
    print(f"  摘要：{report['summary']}")

    has_risks = report["counts"]["total"] > 0
    ok &= has_risks
    print(f"  {'✅' if has_risks else '❌'} 识别到 {report['counts']['total']} 处风险")

    # 字段完整性
    required = ("clause_no", "quote", "risk", "level", "level_label", "suggestion", "located")
    missing_fields = [
        field
        for risk in report["risks"]
        for field in required
        if field not in risk
    ]
    ok &= not missing_fields
    print(f"  {'✅' if not missing_fields else '❌'} 风险条目字段齐全"
          f"{'' if not missing_fields else '：缺 ' + str(set(missing_fields))}")

    located = sum(1 for r in report["risks"] if r["located"])
    print(f"  原文定位：{located}/{len(report['risks'])} 条命中合同原文")

    # 至少有一条引用了真实原文，说明「原文定位」不是摆设
    with_quote = [r for r in report["risks"] if r["quote"]]
    quote_ok = bool(with_quote) and any(r["located"] for r in with_quote)
    ok &= quote_ok
    print(f"  {'✅' if quote_ok else '❌'} 存在可核对的原文摘录")

    for risk in report["risks"][:5]:
        flag = "✓" if risk["located"] else "?"
        print(f"    [{risk['level_label']}] {flag} {risk['clause_title'][:20] or '全文'} | {risk['risk'][:40]}")

    # 写回台账
    detail = client.get(f"{base}/contracts/{contract_id}", headers=headers)
    saved_report = (detail.json() or {}).get("ai_review_report") or {}
    saved_ok = bool(saved_report.get("risks")) and saved_report.get("counts") == report["counts"]
    ok &= saved_ok
    print(f"  {'✅' if saved_ok else '❌'} 报告已写入 contract.ai_review_report")

    reviewed_at = (detail.json() or {}).get("ai_review_at")
    ok &= bool(reviewed_at)
    print(f"  {'✅' if reviewed_at else '❌'} ai_review_at 已更新：{reviewed_at}")
    return ok


# ---------------------------------------------------------------------------
# 4. 权限与入参
# ---------------------------------------------------------------------------


def check_guard(client: httpx.Client, base: str, contract_id: int) -> bool:
    _h("[4] 权限与入参校验")
    ok = True
    staff = _login(client, base, DEFAULT_USER, DEFAULT_PASSWORD)

    # 4.1 客户账号不能审查
    client_h = _login(client, base, CLIENT_USER, CLIENT_PASSWORD)
    resp = client.post(
        f"{base}/ai/review-contract/{contract_id}",
        headers={**client_h, "Accept": "text/event-stream"},
        timeout=60,
    )
    denied = resp.status_code == 403
    ok &= denied
    print(f"  {'✅' if denied else '❌'} 客户账号审查 → {resp.status_code}（期望 403）")

    # 4.2 不存在的合同
    resp = client.post(
        f"{base}/ai/review-contract/999999",
        headers={**staff, "Accept": "text/event-stream"},
        timeout=60,
    )
    not_found = resp.status_code == 404
    ok &= not_found
    print(f"  {'✅' if not_found else '❌'} 不存在的合同 → {resp.status_code}（期望 404）")

    # 4.3 未上传文件且未粘贴正文（合同 9 无 file_url）
    empty_id = 9 if contract_id != 9 else 8
    resp = client.post(
        f"{base}/ai/review-contract/{empty_id}",
        headers={**staff, "Accept": "text/event-stream"},
        timeout=60,
    )
    no_file = resp.status_code in (400, 403)  # 403 表示该合同不归当前律师
    ok &= no_file
    print(f"  {'✅' if no_file else '❌'} 无文件/无权 → {resp.status_code}（期望 400 或 403）")

    # 4.4 正文过短
    resp = client.post(
        f"{base}/ai/review-contract/{contract_id}",
        headers={**staff, "Accept": "text/event-stream"},
        json={"text": "太短了", "save": False},
        timeout=60,
    )
    too_short = resp.status_code == 400
    ok &= too_short
    detail = resp.json().get("detail", "")[:40] if resp.headers.get("content-type", "").startswith("application/json") else ""
    print(f"  {'✅' if too_short else '❌'} 正文过短 → {resp.status_code}（期望 400）{detail}")

    # 4.5 不保存模式：不应该覆盖已存报告
    resp = client.post(
        f"{base}/ai/review-contract/{contract_id}",
        headers={**staff, "Accept": "text/event-stream"},
        json={"text": LONG_CONTRACT, "save": False},
        timeout=600,
    )
    if resp.status_code == 200:
        events = _read_sse(resp)
        unsaved = "done" in events and events["done"][0]["saved"] is False
        ok &= unsaved
        print(f"  {'✅' if unsaved else '❌'} save=false 时返回 saved=False")
    else:
        ok = False
        print(f"  ❌ save=false 请求失败：{resp.status_code}")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="9.5 合同风险审查自测")
    parser.add_argument("--base", default="http://127.0.0.1:8000/api")
    parser.add_argument("--contract-id", type=int, default=8)
    parser.add_argument("--digest", action="store_true", help="只测切分与解析")
    parser.add_argument("--review", action="store_true", help="测 SSE 全链路")
    parser.add_argument("--guard", action="store_true", help="测权限与入参")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()

    if not any((args.digest, args.review, args.guard, args.all)):
        args.all = True

    results: list[bool] = []
    if args.digest or args.all:
        results.append(check_digest())
        results.append(check_parse())

    if args.review or args.guard or args.all:
        with httpx.Client(timeout=600, trust_env=False) as client:
            if args.review or args.all:
                results.append(check_review(client, args.base, args.contract_id))
            if args.guard or args.all:
                results.append(check_guard(client, args.base, args.contract_id))

    passed = sum(1 for item in results if item)
    print(f"\n{'=' * 60}\n结果：{passed}/{len(results)} 项通过\n{'=' * 60}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
