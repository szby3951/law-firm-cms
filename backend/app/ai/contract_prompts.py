"""合同风险审查提示词、风险清单与结构化输出解析（任务拆解 9.5.2 / 9.5.3）。

审查与问答的差别在于**输出必须是可渲染的结构**：律师要的不是一段"该合同存在
若干风险"的散文，而是「哪一条、原文是什么、多严重、怎么改」。所以这里做三件事：

1. **风险清单**：把实务中最常出问题的 14 类条款写成带判据的 ``RiskCheck``，
   逐条列进提示词。清单是「别忘了查」的备忘，也让模型输出的 ``check`` 字段
   可以和清单对应上，前端就能按类目聚合。
2. **JSON 契约**：明确要求 ``{summary, risks[], missing, notes}``，每个风险带
   ``clause / quote / risk / level / suggestion / basis``，其中 ``quote`` 必须是
   原文摘录——这是"原文定位"能成立的前提。
3. **解析容错**（9.5.3）：模型会返回裸数组、中文键名、``"高风险"`` 这种等级写法、
   带 ```json 围栏的输出。:func:`normalize_report` 全部兜住；实在解析不出来由
   ``gateway.generate_json`` 重试一次，仍失败则整体报错，绝不把半截 JSON 存进
   ``contract.ai_review_report``。

**规则预检**（:func:`precheck_risks`）与模型结论并列展示：缺管辖、缺违约责任、
大量空白未填这类判断不需要模型，规则比模型更稳，也更容易向客户解释"为什么说有风险"。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from app.ai.contract_text import ContractDigest, render_clause
from app.ai.llm_clients.base import Message
from app.config import settings

__all__ = [
    "CONTRACT_TYPE_LABELS",
    "DISCLAIMER",
    "LEVELS",
    "LEVEL_LABELS",
    "RISK_CHECKS",
    "RiskCheck",
    "assemble_report",
    "build_review_messages",
    "extract_missing",
    "extract_notes",
    "merge_risks",
    "normalize_level",
    "normalize_report",
    "precheck_risks",
    "render_text",
    "review_meta_block",
    "schema_hint",
]

DISCLAIMER = (
    "AI 审查结果仅供参考，不构成法律意见；风险判断与修改建议须经承办律师复核后使用。"
)

LEVELS = ("high", "mid", "low")
LEVEL_LABELS = {"high": "高", "mid": "中", "low": "低"}

# 报告里 model 字段可能返回这些写法，一律归一到 high/mid/low
_LEVEL_ALIASES = {
    "high": ("high", "高", "严重", "重大", "高风险", "较高风险", "critical", "major", "severe", "3"),
    "mid": ("mid", "medium", "中等", "中", "较高", "一般", "moderate", "normal", "2"),
    "low": ("low", "低", "轻微", "提示", "建议", "minor", "info", "notice", "1"),
}

CONTRACT_TYPE_LABELS = {
    "agency": "委托代理",
    "counsel": "常年法律顾问",
    "litigation": "诉讼代理",
    "non_litigation": "非诉专项",
    "service": "法律服务",
}

CONTRACT_STATUS_LABELS = {
    "draft": "草稿",
    "active": "生效中",
    "expired": "已到期",
    "terminated": "已终止",
}

# 单份报告最多保留的风险条数：超出后前端要翻几十屏，反而没人看
_MAX_RISKS = 40


@dataclass(frozen=True, slots=True)
class RiskCheck:
    """一条审查清单项。

    :param key: 英文标识，模型在 ``check`` 字段回填它，便于前端按类目聚合
    :param label: 中文名称
    :param criterion: 判据——写清"什么情况算风险"，否则模型的判断标准会漂移
    :param level: 命中后的默认等级（模型可上调或下调）
    """

    key: str
    label: str
    criterion: str
    level: str


RISK_CHECKS: tuple[RiskCheck, ...] = (
    RiskCheck(
        "penalty",
        "违约金比例",
        "违约金、逾期付款违约金、滞纳金是否过高（超过合同金额 30%，或日万分之五以上）"
        "或过低到没有约束力；定金是否超过主合同标的额的 20%；"
        "是否同时约定违约金与继续履行、赔偿损失导致重复计算",
        "high",
    ),
    RiskCheck(
        "jurisdiction",
        "争议解决与管辖",
        "是否约定争议解决方式；管辖法院是否明确具体（不能只写「有管辖权的人民法院」）；"
        "是否同时约定仲裁与诉讼；协议管辖是否与争议有实际联系；"
        "仲裁机构名称是否准确唯一",
        "high",
    ),
    RiskCheck(
        "unlimited_liability",
        "责任范围与上限",
        "是否约定无限连带责任、放弃抗辩权或时效抗辩；是否要求股东、法定代表人、"
        "关联方承担连带责任；赔偿责任上限是否缺失、畸低或单方适用",
        "high",
    ),
    RiskCheck(
        "unilateral",
        "权利义务对等性",
        "是否只有一方享有解除权、变更权、最终解释权；是否单方免责、单方加重对方责任；"
        "是否排除对方主要权利、免除己方主要义务（可能构成格式条款无效）",
        "high",
    ),
    RiskCheck(
        "blank",
        "空白与不确定条款",
        "是否存在未填写的空白（【 】、XX、____）；是否大量使用「另行协商」「按惯例」"
        "「视情况」等无法执行的表述；签署主体、日期是否留空",
        "high",
    ),
    RiskCheck(
        "payment",
        "付款与验收",
        "付款节点、比例、期限是否明确；验收标准是否可操作（不能只写「验收合格」）；"
        "发票类型与开具时点；逾期付款的利息或违约金是否约定",
        "mid",
    ),
    RiskCheck(
        "termination",
        "解除与终止",
        "是否约定解除条件与解除程序；解除后的费用结算、已付款项处理、"
        "资料与成果交接是否明确；是否约定终止后的存续条款",
        "mid",
    ),
    RiskCheck(
        "auto_renewal",
        "自动续约",
        "是否约定自动续约、自动延期而缺少异议期或退出机制；续约后的价格与范围是否明确",
        "mid",
    ),
    RiskCheck(
        "confidentiality_ip",
        "保密与知识产权",
        "保密范围、期限、违约后果是否明确；成果与知识产权归属、许可使用范围、"
        "第三方素材授权是否约定",
        "mid",
    ),
    RiskCheck(
        "subject",
        "主体与签署",
        "当事人名称与证件号/统一社会信用代码是否齐全；签约主体与实际履行主体是否一致；"
        "签署人是否有授权；生效条件（签字/盖章/付款）是否明确；份数与持有一致性",
        "mid",
    ),
    RiskCheck(
        "scope",
        "服务范围与权限",
        "委托事项、代理权限（一般/特别授权）是否明确；是否包含二审、执行、"
        "另行委托的程序；超出约定范围的工作如何计费；案外和解的授权边界",
        "mid",
    ),
    RiskCheck(
        "fee_compliance",
        "收费合规",
        "风险代理比例是否超过法定上限（现行规定不超过标的额 30%）；"
        "是否属于禁止风险代理的案件类型（刑事、行政、国家赔偿及群体性案件）；"
        "代理费与诉讼费、差旅费、鉴定费等第三方费用的边界是否清晰；退费规则是否合理",
        "high",
    ),
    RiskCheck(
        "force_majeure",
        "不可抗力",
        "不可抗力范围是否过宽（把市场价格波动、政策变化等商业风险纳入）或过窄；"
        "通知期限、证明文件与减损义务是否约定",
        "low",
    ),
    RiskCheck(
        "notice",
        "通知与送达",
        "是否约定送达地址、电子送达方式及地址变更的通知义务；"
        "约定送达地址能否适用于诉讼文书送达",
        "low",
    ),
)

_COMMON_RULES = """## 审查原则
1. 只依据【合同条款】中出现的文字判断。不臆测未提供的附件、往来函件、口头承诺，
   也不假设"通常会有"的条款存在。
2. 每条风险必须给出 `quote`：从合同中**原样摘录**的连续片段（10~60 字），不得改写、
   归纳、拼接或翻译。摘不出原文时宁可不报这条风险。
3. `level` 取值：high = 可能导致重大损失、条款无效或无法执行；mid = 需要修改或补充
   约定才能有效执行；low = 表述与细节优化。
4. `suggestion` 必须可直接落到条款上：改成什么、补什么、删什么、比例改成多少。
   不要写"建议完善相关条款""注意风险"这类空话。
5. `basis` 只在确有把握时填写法律依据，写法律全称与条号（如《中华人民共和国民法典》
   第五百八十五条）；不确定就留空字符串，**不得编造**法条、司法解释编号或案例编号。
6. 合同对委托方有利、条款完备的部分不要凑数报风险；没有风险就返回空数组。
7. 不对合同的商业价值、对方当事人的资信发表意见，只审条款。
8. 一次最多报 8 条风险，按严重程度取最需要处理的。`quote` 只摘一句原文、40 字
   以内、不要跨行拼接多个条款——结构化的报告比面面俱到更有用，列表太长反而没人看。"""

_SYSTEM_PROMPT = """你是「{firm}」的资深合同审查律师，正在为委托方审查一份合同文本，
目标是找出对委托方不利、约定不明或无法执行的条款。

{common_rules}

## 输出格式
只输出一个 JSON 对象，不要 Markdown 代码块、不要任何解释文字：
{schema}
"""

_USER_TEMPLATE = """【合同信息】
{meta}

【系统预检】以下由规则初筛，供参考，不代替你的审查：
{precheck}

【审查清单】逐条对照，命中才报，不要为每条清单都编一条风险：
{checklist}

【合同条款】{batch_note}
{clauses}
{focus_block}
请输出 JSON 结果。"""


def schema_hint() -> str:
    """给模型看的 JSON 契约（同时用于 ``generate_json`` 的 schema_hint）。"""
    return json.dumps(
        {
            "summary": "一句话总体结论，含风险数量与最需要处理的两三处",
            "risks": [
                {
                    "clause": "第X条 条款标题（用【条款 N】的编号）",
                    "quote": "原样摘录的合同原文，10~60 字",
                    "risk": "该条对委托方的不利后果，说明为什么是风险",
                    "level": "high|mid|low",
                    "suggestion": "具体改法",
                    "basis": "法律依据，可空字符串",
                    "check": "清单 key，如 penalty/jurisdiction",
                }
            ],
            "missing": ["合同中完全缺失、但本应有的事项，如「争议解决条款」"],
            "notes": "其他需要提醒律师的内容，可空字符串",
        },
        ensure_ascii=False,
    )


def review_meta_block(meta: dict[str, Any], digest: ContractDigest) -> str:
    """合同基本信息 + 文本规模，帮助模型判断"这是律所委托合同还是商务合同"。"""
    lines = [
        f"- 合同名称：{meta.get('name') or '未命名'}",
        f"- 合同类型：{meta.get('type_label') or '未标注'}",
        f"- 合同金额：{meta.get('amount_text') or '未填写'}",
        f"- 起止日期：{meta.get('period_text') or '未填写'}",
    ]
    if meta.get("client_name"):
        lines.append(f"- 委托客户：{meta['client_name']}")
    if meta.get("case_title"):
        lines.append(f"- 关联案件：{meta['case_title']}")
    if meta.get("status_label"):
        lines.append(f"- 合同状态：{meta['status_label']}")
    source_label = {
        "docx": "Word 文件",
        "pdf": "PDF 文件",
        "txt": "文本文件",
        "md": "Markdown 文件",
        "paste": "律师粘贴的正文",
    }.get(digest.source, digest.source)
    scale = f"- 文本规模：{digest.char_count} 字，切分为 {digest.clause_count} 个条款"
    if digest.truncated:
        scale += "（合同过长，仅审查前部条款）"
    lines.append(f"- 文本来源：{source_label}")
    lines.append(scale)
    return "\n".join(lines)


def _precheck_block(digest: ContractDigest) -> str:
    """把规则初筛结果写进提示词，让模型先看"哪里可能缺"。"""
    lines: list[str] = []
    if digest.elements:
        index = "；".join(
            f"{name}：第{'、'.join(str(no) for no in numbers)}条"
            for name, numbers in digest.elements.items()
        )
        lines.append(f"- 关键词命中的条款（仅供参考）：{index}")
    else:
        lines.append("- 关键词未命中任何条款，合同可能缺少必要的结构")
    if digest.missing:
        lines.append(
            "- 未检索到以下必备条款："
            + "、".join(digest.missing)
            + "。请确认是否确实缺失，缺失的写入 missing 数组"
        )
    if digest.placeholder_count:
        samples = "；".join(
            f"第{item['clause_no']}条「{item['sample']}」"
            for item in digest.placeholders[:4]
        )
        lines.append(
            f"- 检测到 {digest.placeholder_count} 处未填写的空白或占位（如 {samples}）"
        )
    return "\n".join(lines)


def _checklist_block() -> str:
    return "\n".join(
        f"{index}. [{check.key}] {check.label}（默认 {LEVEL_LABELS[check.level]} 风险）："
        f"{check.criterion}"
        for index, check in enumerate(RISK_CHECKS, 1)
    )


def build_review_messages(
    *,
    digest: ContractDigest,
    meta: dict[str, Any],
    clauses: list,
    batch_index: int = 1,
    batch_total: int = 1,
    focus: str | None = None,
) -> list[Message]:
    """组装一批条款的审查提示词。

    :param clauses: 本批要审查的 ``Clause`` 列表（条号是全文编号，不随批次重置）
    """
    batch_note = ""
    if batch_total > 1:
        batch_note = (
            f"（本次为全文第 {batch_index}/{batch_total} 批，只审查下列条款；"
            "不要评价未提供的条款，也不要因为看不到其他条款就说某事项缺失）"
        )

    focus_block = ""
    if focus and focus.strip():
        focus_block = f"\n【律师特别关注】\n{focus.strip()}\n"

    user_content = _USER_TEMPLATE.format(
        meta=review_meta_block(meta, digest),
        precheck=_precheck_block(digest),
        checklist=_checklist_block(),
        batch_note=batch_note,
        clauses="\n\n".join(render_clause(clause) for clause in clauses),
        focus_block=focus_block,
    )

    return [
        {
            "role": "system",
            "content": _SYSTEM_PROMPT.format(
                firm=settings.firm_name,
                common_rules=_COMMON_RULES,
                schema=schema_hint(),
            ),
        },
        {"role": "user", "content": user_content},
    ]


# ---------------------------------------------------------------------------
# 解析与归一（9.5.3）
# ---------------------------------------------------------------------------


def normalize_level(value: Any) -> str:
    """把各种等级写法归一成 ``high`` / ``mid`` / ``low``。"""
    text = str(value or "").strip().lower()
    if not text:
        return "mid"
    # 「高风险」「HIGH」「3」这类先粗匹配
    for level, aliases in _LEVEL_ALIASES.items():
        if text in aliases:
            return level
    for level, aliases in _LEVEL_ALIASES.items():
        if any(alias in text for alias in aliases if len(alias) >= 2):
            return level
    return "mid"


def _first(item: dict, *keys: str) -> Any:
    for key in keys:
        value = item.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _clamp(text: str, limit: int) -> str:
    """超长文本截断并加省略号，避免一条「缺失项」占掉半屏。"""
    text = " ".join((text or "").split())
    return text if len(text) <= limit else f"{text[:limit]}…"


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "；".join(_as_text(v) for v in value if v)
    if isinstance(value, dict):
        return "；".join(f"{k}：{_as_text(v)}" for k, v in value.items() if v)
    return str(value).strip()


def _extract_items(raw: Any) -> list[dict]:
    """从模型输出里抠出风险数组，兼容裸数组与多种键名。"""
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if not isinstance(raw, dict):
        return []

    for key in ("risks", "风险点", "风险列表", "风险项", "items", "list", "data", "result"):
        value = raw.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]

    # 只有一个风险对象的情况
    if any(key in raw for key in ("risk", "风险", "风险说明", "level", "风险等级")):
        return [raw]
    return []


def normalize_report(raw: Any, digest: ContractDigest, *, source: str = "ai") -> list[dict]:
    """把模型输出（或历史报告）归一成前端可渲染的风险列表。

    - 兼容中文键名与裸数组；
    - 用 :meth:`ContractDigest.locate` 校验 ``quote`` 是否真在合同里，否则
      ``located=False``，前端提示人工核对（不隐藏该风险，也不伪造原文）；
    - 无 ``quote`` 的风险保留，但同样标记为未定位。
    """
    risks: list[dict] = []
    for item in _extract_items(raw):
        quote = _as_text(_first(item, "quote", "原文定位", "原文", "引用", "excerpt", "location"))
        # 设计文档里的键名是「风险条款」，它指的是风险本身而不是条款标题，
        # 所以优先当作 risk；条款位置由 quote 定位或从「第X条」文字反查。
        risk = _as_text(
            _first(
                item,
                "risk",
                "风险说明",
                "风险",
                "风险条款",
                "desc",
                "description",
                "issue",
                "problem",
            )
        )
        clause_hint = _as_text(
            _first(item, "clause", "条款", "条款名称", "clause_title", "article", "条款位置")
        ) or risk
        suggestion = _as_text(
            _first(item, "suggestion", "修改建议", "建议", "advice", "fix", "recommendation")
        )
        basis = _as_text(_first(item, "basis", "法律依据", "依据", "law", "legal_basis"))
        check = _as_text(_first(item, "check", "清单", "check_key", "category"))
        level = normalize_level(_first(item, "level", "风险等级", "等级", "severity"))

        if not (risk or quote or suggestion):
            continue

        clause_no, located = digest.locate(quote) if quote else (None, False)
        clause = _pick_clause(digest, clause_no, clause_hint)

        risks.append(
            {
                "clause_no": clause.no if clause else None,
                "clause_title": clause.title if clause else clause_hint[:60],
                "quote": quote[:200],
                "risk": risk or "（模型未说明风险内容，请人工核对）",
                "level": level,
                "level_label": LEVEL_LABELS[level],
                "suggestion": suggestion or "请人工补充修改方案",
                "basis": basis,
                "check": check,
                "check_label": _check_label(check),
                "located": located,
                "source": source,
            }
        )
    return risks


def _short_label(text: str, limit: int = 14) -> str:
    """把模型写的长句压成一个短标签（用于摘要里的「未见……」）。"""
    head = re.split(r"[：:，,。；;（(]", text or "")[0].strip()
    head = head or (text or "").strip()
    return head if len(head) <= limit else f"{head[:limit]}…"


def extract_missing(raw: Any) -> list[str]:
    """取模型报告的「合同中缺失的事项」，兼容多种键名与单字符串写法。"""
    if not isinstance(raw, dict):
        return []
    for key in ("missing", "缺失条款", "missing_clauses", "缺失项"):
        value = raw.get(key)
        if isinstance(value, list):
            items = [_as_text(v) for v in value if _as_text(v)]
            return [_clamp(item, 60) for item in items]
        if isinstance(value, str) and value.strip():
            return [_clamp(value.strip(), 60)]
    return []


def extract_notes(raw: Any) -> str:
    """取模型的补充说明（备注/notes），用于报告 notes 字段。"""
    if not isinstance(raw, dict):
        return ""
    return _as_text(_first(raw, "notes", "备注", "说明", "note"))[:400]


def _check_label(key: str) -> str:
    if not key:
        return ""
    for check in RISK_CHECKS:
        if check.key == key or check.label in key or key in check.label:
            return check.label
    return ""


def _pick_clause(digest: ContractDigest, clause_no: int | None, hint: str):
    """优先按 quote 定位到的条号，其次按模型给的「第X条」文字反查。"""
    if clause_no:
        for clause in digest.clauses:
            if clause.no == clause_no:
                return clause
    if hint:
        match = re.search(r"第\s*(\d+)\s*条", hint)
        if match:
            no = int(match.group(1))
            for clause in digest.clauses:
                if clause.no == no:
                    return clause
        # 「第四条 违约责任」——按标题前缀匹配
        for clause in digest.clauses:
            if hint[:8] and hint[:8] in clause.title:
                return clause
    return None


def _risk_key(risk: dict) -> str:
    """跨批次去重用的键：同一条款 + 同一段原文（或同一风险描述前缀）。"""
    quote = re.sub(r"\s+", "", risk.get("quote") or "")
    if risk.get("clause_no") and quote:
        return f"{risk['clause_no']}|{quote[:40]}"
    text = re.sub(r"\s+", "", risk.get("risk") or "")
    return f"{risk.get('clause_no') or 0}|{text[:30]}"


def merge_risks(*groups: list[dict]) -> list[dict]:
    """合并多批结果，重复项保留等级更高的一条（同等级保留先出现的）。"""
    order = {level: index for index, level in enumerate(LEVELS)}
    merged: dict[str, dict] = {}
    for group in groups:
        for risk in group:
            key = _risk_key(risk)
            existing = merged.get(key)
            if existing is None:
                merged[key] = risk
                continue
            higher = order[risk["level"]] < order[existing["level"]]
            prefer_ai = risk.get("source") == "ai" and existing.get("source") != "ai"
            if higher or prefer_ai:
                merged[key] = risk

    risks = sorted(
        merged.values(),
        key=lambda r: (order[r["level"]], r.get("clause_no") or 999, len(r.get("risk") or "")),
    )
    for index, risk in enumerate(risks, 1):
        risk["id"] = index
    return risks


def precheck_risks(digest: ContractDigest) -> list[dict]:
    """规则预检：缺条款、大量空白这两类不需要模型也能判断的风险。

    与模型结果并列呈现而不是互相替代——规则可能误判（比如"解除"写在其他条款里），
    模型也可能漏看，两边都摆出来让律师自己判断。
    """
    risks: list[dict] = []
    missing_rules = {
        "争议解决": (
            "high",
            "合同未约定争议解决方式与管辖法院，发生纠纷时可能先陷入管辖争议，也可能被迫到对方所在地应诉",
            "增加争议解决条款：明确协商不成的处理方式，并在「向有管辖权的人民法院起诉」与「提交某仲裁委员会仲裁」中择一；协议管辖法院需与争议有实际联系",
            "jurisdiction",
        ),
        "违约责任": (
            "high",
            "合同未约定违约责任，一方违约时守约方只能就实际损失举证，举证成本高且难以覆盖预期利益损失",
            "补充违约责任条款：明确逾期付款/逾期履行的违约金计算方式（比例与起算日）、根本违约的解除权与赔偿责任",
            "penalty",
        ),
        "金额与费用": (
            "high",
            "合同未明确金额或费用条款，履行中极易就价款产生争议",
            "明确费用总额、计费方式、支付节点与发票开具要求；区分代理费与诉讼费、差旅费等第三方费用",
            "payment",
        ),
        "期限与生效": (
            "mid",
            "合同未约定生效条件或履行期限，双方权利义务的起止时点不明确",
            "补充生效条件（签字并盖章/付款之日）、服务期限与到期后的处理方式",
            "subject",
        ),
        "主体信息": (
            "mid",
            "合同当事人信息不完整，主体不明会影响主张权利与送达",
            "补全双方名称、证件号或统一社会信用代码、住所地与联系方式",
            "subject",
        ),
        "标的与范围": (
            "mid",
            "合同未明确服务/委托范围，容易产生「这活到底包不包含」的争议",
            "列明服务事项清单与代理权限（一般/特别授权），明确超出范围的工作如何计费",
            "scope",
        ),
    }
    for dimension in digest.missing:
        rule = missing_rules.get(dimension)
        if not rule:
            continue
        level, risk, suggestion, check = rule
        risks.append(
            {
                "clause_no": None,
                "clause_title": "",
                "quote": "",
                "risk": f"未检索到「{dimension}」相关条款：{risk}",
                "level": level,
                "level_label": LEVEL_LABELS[level],
                "suggestion": suggestion,
                "basis": "",
                "check": check,
                "check_label": _check_label(check),
                "located": False,
                "source": "precheck",
            }
        )

    if digest.placeholder_count >= 5:
        samples = "；".join(
            f"第{item['clause_no']}条「{item['sample']}」" for item in digest.placeholders[:3]
        )
        risks.append(
            {
                "clause_no": digest.placeholders[0]["clause_no"] if digest.placeholders else None,
                "clause_title": "",
                "quote": digest.placeholders[0]["sample"] if digest.placeholders else "",
                "risk": (
                    f"合同存在 {digest.placeholder_count} 处未填写的空白或占位"
                    f"（如 {samples}），签署前未补全将导致相关条款无法执行或约定不明"
                ),
                "level": "mid",
                "level_label": LEVEL_LABELS["mid"],
                "suggestion": "逐项补全空白；无法确定的条款删除或改为明确的处理规则，"
                "避免以「XX」「【 】」形式签署",
                "basis": "",
                "check": "blank",
                "check_label": _check_label("blank"),
                "located": bool(digest.placeholders),
                "source": "precheck",
            }
        )
    return risks


def _drop_duplicated_precheck(risks: list[dict]) -> list[dict]:
    """模型已就同一清单项报过风险时，丢掉规则预检的那条，避免重复刷屏。"""
    ai_checks = {risk["check"] for risk in risks if risk["source"] == "ai" and risk["check"]}
    ai_text = "".join(risk["risk"] for risk in risks if risk["source"] == "ai")
    kept: list[dict] = []
    for risk in risks:
        if risk["source"] != "precheck":
            kept.append(risk)
            continue
        if risk["check"] and risk["check"] in ai_checks:
            continue
        if risk["check"] == "jurisdiction" and "管辖" in ai_text:
            continue
        if risk["check"] == "blank" and ("空白" in ai_text or "未填写" in ai_text):
            continue
        kept.append(risk)
    return kept


# ---------------------------------------------------------------------------
# 报告组装
# ---------------------------------------------------------------------------


def assemble_report(
    *,
    meta: dict[str, Any],
    digest: ContractDigest,
    risks: list[dict],
    missing: list[str],
    notes: list[str],
    model: str,
    provider: str,
    reviewed_at: str,
    batches: int,
    token_usage: int = 0,
) -> dict[str, Any]:
    """把合并后的风险列表组装成落库/前端共用的报告结构。"""
    risks = _drop_duplicated_precheck(risks)
    if len(risks) > _MAX_RISKS:
        risks = risks[:_MAX_RISKS]
        notes = [
            *notes,
            f"风险条目超过 {_MAX_RISKS} 条，报告仅保留优先级最高的部分，其余请对照条款人工核对",
        ]
    for index, risk in enumerate(risks, 1):
        risk["id"] = index

    counts = {level: sum(1 for r in risks if r["level"] == level) for level in LEVELS}
    counts["total"] = len(risks)
    overall = "none"
    for level in LEVELS:
        if counts[level]:
            overall = level
            break

    return {
        "version": 1,
        "summary": _build_summary(risks, counts, missing),
        "level": overall,
        "level_label": LEVEL_LABELS.get(overall, "无"),
        "counts": counts,
        "risks": risks,
        "missing": missing,
        "notes": [note for note in notes if note],
        "precheck": {
            "elements": digest.elements,
            "missing_dimensions": digest.missing,
            "placeholder_count": digest.placeholder_count,
            "placeholders": digest.placeholders,
        },
        "contract": {
            "id": meta.get("id"),
            "name": meta.get("name"),
            "type_label": meta.get("type_label"),
            "amount_text": meta.get("amount_text"),
            "period_text": meta.get("period_text"),
            "char_count": digest.char_count,
            "clause_count": digest.clause_count,
            "source": digest.source,
            "batches": batches,
            "truncated": digest.truncated,
        },
        "model": model,
        "provider": provider,
        "reviewed_at": reviewed_at,
        "token_usage": token_usage,
        "disclaimer": DISCLAIMER,
    }


def _build_summary(risks: list[dict], counts: dict[str, int], missing: list[str]) -> str:
    """用统计而不是模型生成的 summary：数量与等级一定和列表对得上。"""
    if not risks:
        return "未发现明显风险条款。建议律师结合商业背景与附件再行复核。"

    parts = [
        f"共识别 {counts['total']} 处风险（高 {counts['high']} / 中 {counts['mid']} / 低 {counts['low']}）。"
    ]
    highlights = [risk for risk in risks if risk["level"] in ("high", "mid")][:2]
    if highlights:
        names = "、".join(
            (risk["check_label"] or risk["clause_title"] or "条款风险") for risk in highlights
        )
        parts.append(f"优先处理：{names}。")
    if missing:
        labels = "、".join(_short_label(item) for item in missing[:3])
        parts.append(f"合同中未见「{labels}」相关内容。")
    return "".join(parts)


def render_text(report: dict[str, Any]) -> str:
    """把报告渲染成纯文本，落进 ``ai_message.content`` 供审计与历史回看。"""
    lines = [f"【AI 合同风险审查】{report.get('contract', {}).get('name') or ''}"]
    lines.append(report.get("summary") or "")
    for risk in report.get("risks") or []:
        head = f"[{risk.get('level_label')}] {risk.get('clause_title') or '全文'}"
        if risk.get("check_label"):
            head += f" · {risk['check_label']}"
        lines.append(head)
        if risk.get("quote"):
            lines.append(f"  原文：{risk['quote']}")
        lines.append(f"  风险：{risk.get('risk')}")
        lines.append(f"  建议：{risk.get('suggestion')}")
        if risk.get("basis"):
            lines.append(f"  依据：{risk['basis']}")
    if report.get("missing"):
        lines.append(f"缺失条款：{'、'.join(report['missing'])}")
    for note in report.get("notes") or []:
        lines.append(f"备注：{note}")
    lines.append(report.get("disclaimer") or DISCLAIMER)
    return "\n".join(lines)
