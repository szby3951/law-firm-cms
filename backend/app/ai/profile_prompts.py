"""客户画像提示词与 JSON 规范化（任务拆解 9.7.3）。

客户画像和前面几项 AI 能力的区别在于**输出是结构化字段，而不是一段文章**：
它要写回 ``client_profile.ai_profile``，给客户列表页做标签、给跟进提醒做依据，
所以必须先保证「每次都是同一组键、同样的类型」，再谈内容质量。

字段按任务拆解 9.7.3 的模板固定为五项——客户类型 / 核心诉求 / 风险点 /
沟通偏好 / 下一步跟进建议——另外补三项便于落地使用的元信息：

- ``标签``：3~5 个短词，列表页和检索可复用；
- ``数据依据``：每条判断对应哪条跟进/案件/回款，方便律师核对；
- ``数据缺口``：哪些信息档案里没有，决定画像的可信边界。

**画像不是算命。** 客户档案往往只有几条跟进、一两个案件，模型很容易顺着常识
把「中小企业主」写成「有跨境业务需求」。提示词因此强制：只依据给定数据、每条
判断标注依据、数据不足就写「数据不足」并列入缺口、不推测性别年龄职业等未登记
信息。这是本模块和普通"客户分析"最大的区别。

**送入模型前脱敏（9.7.4）。** 身份证、手机号、邮箱、详细地址与个人姓名都在
:mod:`app.services.client_profile_service` 里打码。姓名打码后模型看到的是
「张*」，因此提示词额外要求：不得还原或猜测被脱敏内容，输出统一用「该客户」
指代，避免画像里出现半截姓名。

**输出不可信。** 模型返回的 JSON 会经过 :func:`normalize_profile` 逐字段清洗：
类型不对就转、超长就截、必填项为空就判为无效。只有通过校验的结果才会写库。
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.ai.llm_clients.base import Message
from app.config import settings

__all__ = [
    "DISCLAIMER",
    "FIELDS",
    "MAX_RISKS",
    "PROFILE_SCHEMA_HINT",
    "ProfileFormatError",
    "build_profile_messages",
    "build_system_prompt",
    "normalize_profile",
    "parse_json_object",
]

DISCLAIMER = (
    "AI 客户画像由客户档案、跟进记录、案件、合同、收费与沟通数据自动归纳，"
    "仅供负责律师内部参考，可能因数据不全而失准；涉及客户决策前请人工核对。"
)

# 模型偶尔会违反"最多 3 条"，这里兜底截断，避免风险点变成一长串清单
MAX_RISKS = 3
MAX_TAGS = 6
# 各字段的长度上限：前端按卡片展示，过长会挤爆布局，也说明模型在凑字数
_LIMITS = {
    "client_type": 40,
    "core_demands": 300,
    "communication": 240,
    "next_actions": 700,
    "tag": 12,
    "risk_point": 160,
    "risk_basis": 200,
    "risk_action": 200,
    "evidence": 200,
    "gap": 200,
}

# 给网关的 schema 提示：不要求模型理解 Python 类型，只照抄键名与形状
PROFILE_SCHEMA_HINT = (
    '{"客户类型": "8~20字，如「本地制造业中小企业主，决策快、价格敏感」", '
    '"核心诉求": "一段话，写清最想解决的问题与紧迫程度", '
    '"风险点": [{"风险": "一句话", "依据": "来自哪条跟进/案件/回款", '
    '"应对": "可执行的应对动作"}], '
    '"沟通偏好": "时间段、渠道、决策链、对术语/价格的敏感点", '
    '"下一步跟进建议": "2~4 条，用 1. 2. 3. 编号，写清动作与时点", '
    '"标签": ["3~5个短词"], '
    '"数据依据": ["每条判断对应的事实"], '
    '"数据缺口": ["档案中缺失、影响判断的信息"]}'
)

FIELDS = (
    "客户类型",
    "核心诉求",
    "风险点",
    "沟通偏好",
    "下一步跟进建议",
    "标签",
    "数据依据",
    "数据缺口",
)


class ProfileFormatError(ValueError):
    """模型输出无法解析成合法画像。由调用方转成重试或友好报错。"""


def build_system_prompt() -> str:
    """系统提示词：角色 + 硬规则 + JSON 形状 + 每个字段怎么写。"""
    return f"""你是「{settings.firm_name}」的资深客户经理，负责根据律师录入的客户\
数据，为负责律师生成一份可直接指导下一步跟进的客户画像。

【必须遵守】
1. 只使用给定数据。数据没有登记的，不要凭常识补全行业、规模、年龄、性别、\
职业、家庭情况、资产状况或法律需求。
2. 每条判断都要能对应到具体事实（哪条跟进、哪个案件、哪笔回款），写在「数据依据」里；\
只写「跟进记录显示客户三次提到回款压力」这种可核对的表述，不写「客户资金链紧张」这种结论\
而没有任何依据。
3. 数据不足以支撑某项判断时，该项写「数据不足」，并把缺什么写进「数据缺口」，\
不要用推测填空。
4. 姓名、电话、证件号、地址已做脱敏（如「张*」「138****8000」）。严禁还原、\
猜测或拼凑被脱敏的内容；指代客户时统一用「该客户」，不要复述脱敏后的姓名。
5. 风险点最多 3 条，按对「合作能否继续、能否回款、是否可能投诉」的影响排序；\
每条必须写清风险、依据与应对。
6. 「下一步跟进建议」要具体可执行：写清做什么、什么时候做、为什么现在做；\
结合客户当前的漏斗状态（潜在/成交/流失）与最近一次跟进。不要写「加强沟通」\
「保持联系」这类空话。
7. 不做法律意见，不预测案件结果，不评价律师办案质量。

【输出格式】
- 严格只输出一个 JSON 对象，不要 Markdown 代码围栏、不要解释文字、不要注释。
- 键名必须是下列中文键，不得增删改名；数组字段必须是 JSON 数组。
- 形状：
{PROFILE_SCHEMA_HINT}

【每个字段写什么】
- 客户类型：用一句话刻画这位客户是谁、处在什么决策位置（个人/机构、\
行业或身份、决策快慢、价格敏感度），不要写成联系人姓名或「个人客户」四个字。
- 核心诉求：他最想解决的问题、最在意的结果、紧迫程度；多个诉求按轻重排序。
- 风险点：可能影响委托继续、费用回收或引发投诉的因素（如预期过高、\
决策链不清、付款拖延、沟通失联、需求反复）。没有明显风险时输出空数组。
- 沟通偏好：偏好的渠道与时段、对术语/价格/进度的关注点、需要谁拍板。
- 下一步跟进建议：2~4 条编号短句，每条含动作与时点。
- 标签：3~5 个 2~6 字短词，如「价格敏感」「决策链长」「回款及时」。
- 数据依据：3~8 条，说明画像里最关键判断来自哪条记录。
- 数据缺口：档案缺失但影响判断的信息；没有明显缺口时输出空数组。
"""


def _section(title: str, lines: list[str], empty: str) -> list[str]:
    """统一的段落拼装：标题 + 列表，空数据时给一句明确说明。"""
    block = ["", f"【{title}】"]
    block.extend(lines if lines else [empty])
    return block


def build_profile_messages(
    *,
    meta: dict[str, str],
    follows: list[str],
    cases: list[str],
    contracts: list[str],
    billing: list[str],
    messages: list[str],
    skipped: list[str],
    focus: str | None = None,
) -> list[Message]:
    """拼装客户画像的对话消息。

    所有 ``*`` 列表都已在服务层格式化并截断，这里只负责排版——提示词模块不查库，
    也不做预算裁剪，便于单测直接断言拼装结果。

    :param meta: 客户档案键值对（中文键，值已脱敏）
    :param follows: 跟进记录，一条一行，含方式/时间/内容/下次跟进
    :param cases: 关联案件摘要，一条一行
    :param contracts: 合同摘要，一条一行
    :param billing: 收费方案与回款情况，一条一行
    :param messages: 沟通留言摘要，一条一行
    :param skipped: 未纳入或读取失败的数据说明
    :param focus: 律师本次特别关注点
    """
    lines: list[str] = ["【客户基本信息】"]
    lines.extend(f"- {key}：{value}" for key, value in meta.items() if value)
    if len(lines) == 1:
        lines.append("（档案未填写基本信息）")

    lines += _section("跟进记录", follows, "（无跟进记录，无法判断沟通偏好与推进节奏）")
    lines += _section("关联案件", cases, "（无关联案件，尚不能判断委托深度）")
    lines += _section("合同", contracts, "（无合同记录）")
    lines += _section("收费与回款", billing, "（无收费方案，无法判断付费意愿与回款风险）")
    lines += _section("沟通记录", messages, "（无沟通留言）")

    if skipped:
        lines.append("")
        lines.append("【未纳入或无法读取的数据】")
        lines.extend(f"- {item}" for item in skipped)

    if focus:
        lines.append("")
        lines.append("【本次关注点】")
        lines.append(focus.strip())

    lines.append("")
    lines.append(
        "请按系统要求只输出一个 JSON 对象。再次提醒：数据未登记的内容写「数据不足」，"
        "不要推测；不要还原脱敏信息。"
    )
    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": "\n".join(lines).strip()},
    ]


_FENCE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$", re.MULTILINE)


def parse_json_object(text: str) -> dict[str, Any]:
    """从模型输出里取出 JSON 对象。

    模型常见的三种偏差都要兼容：整段包在 ```json 围栏里、前后带一句解释、
    返回了数组。前两种剥掉外壳再解析；数组无法表达画像字段，直接判失败。
    """
    raw = (text or "").strip()
    if not raw:
        raise ProfileFormatError("模型未返回内容")
    raw = _FENCE.sub("", raw).strip()

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # 兜底：截取第一个 { 到最后一个 }，容忍前后夹带的说明文字
        start, end = raw.find("{"), raw.rfind("}")
        if start < 0 or end <= start:
            raise ProfileFormatError("模型输出不是 JSON 对象") from None
        try:
            data = json.loads(raw[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ProfileFormatError(f"JSON 解析失败：{exc.msg}") from exc

    if not isinstance(data, dict):
        raise ProfileFormatError("模型输出的 JSON 不是对象")
    return data


# 中英文键互相兼容：提示词用中文，但不同模型偶尔会自译键名
_ALIASES = {
    "client_type": ("客户类型", "client_type", "type", "客户画像", "类型"),
    "core_demands": ("核心诉求", "core_demands", "诉求", "主要诉求"),
    "risks": ("风险点", "risks", "风险"),
    "communication": ("沟通偏好", "communication", "communication_preference", "沟通习惯"),
    "next_actions": (
        "下一步跟进建议",
        "next_actions",
        "跟进建议",
        "下一步建议",
        "建议",
    ),
    "tags": ("标签", "tags", "画像标签"),
    "evidence": ("数据依据", "evidence", "依据", "判断依据"),
    "gaps": ("数据缺口", "gaps", "缺口", "信息缺口"),
}


def _pick(data: dict[str, Any], key: str) -> Any:
    for alias in _ALIASES[key]:
        if alias in data and data[alias] not in (None, ""):
            return data[alias]
    return None


def _text(value: Any, limit: int) -> str:
    """把任意值压成一行文本并截断。嵌套对象/数组序列化后保留信息，不静默丢弃。"""
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (list, tuple)):
        text = "；".join(_text(item, limit) for item in value if item not in (None, ""))
    elif isinstance(value, dict):
        text = "；".join(
            f"{k}：{_text(v, limit)}" for k, v in value.items() if v not in (None, "")
        )
    else:
        text = str(value)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit].rstrip() if len(text) > limit else text


def _as_list(value: Any) -> list[Any]:
    """字符串按换行/分号拆成列表；单值包成单元素列表。"""
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, str):
        parts = re.split(r"[\n;；]+", value)
        return [part.strip(" -·\t") for part in parts if part.strip(" -·\t")]
    return [value]


def _normalize_risks(value: Any) -> list[dict[str, str]]:
    """风险点统一成 ``{point, basis, action}``。

    模型可能返回纯字符串数组、也可能用「风险/依据/应对」或英文键；元素是字符串时
    整句当作风险描述，依据留空——宁可少写，也不要把风险拆成不存在的依据。
    """
    risks: list[dict[str, str]] = []
    for item in _as_list(value):
        if isinstance(item, dict):
            point = _text(
                item.get("风险") or item.get("point") or item.get("risk"), _LIMITS["risk_point"]
            )
            basis = _text(
                item.get("依据") or item.get("basis") or item.get("evidence"),
                _LIMITS["risk_basis"],
            )
            action = _text(
                item.get("应对") or item.get("action") or item.get("建议"),
                _LIMITS["risk_action"],
            )
        else:
            point = _text(item, _LIMITS["risk_point"])
            basis, action = "", ""
        if not point:
            continue
        risks.append({"point": point, "basis": basis, "action": action})
        if len(risks) >= MAX_RISKS:
            break
    return risks


def _normalize_tags(value: Any) -> list[str]:
    tags: list[str] = []
    for item in _as_list(value):
        tag = _text(item, _LIMITS["tag"])
        if tag and tag not in tags:
            tags.append(tag)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def _normalize_lines(value: Any, limit: int) -> list[str]:
    lines: list[str] = []
    for item in _as_list(value):
        text = _text(item, limit)
        if text and text not in lines:
            lines.append(text)
    return lines


def normalize_profile(data: dict[str, Any]) -> dict[str, Any]:
    """把模型返回的 JSON 清洗成固定结构。

    :raises ProfileFormatError: ``客户类型`` 与 ``核心诉求`` 同时为空——说明模型
        没有按格式回答，继续保存只会污染 ``ai_profile`` 字段。
    """
    client_type = _text(_pick(data, "client_type"), _LIMITS["client_type"])
    core_demands = _text(_pick(data, "core_demands"), _LIMITS["core_demands"])
    if not client_type and not core_demands:
        raise ProfileFormatError("画像缺少「客户类型」与「核心诉求」")

    # 跟进建议是编号短句，压平后把编号前的位置还原成换行，前端可直接按行渲染
    next_actions = _text(_pick(data, "next_actions"), _LIMITS["next_actions"])
    next_actions = re.sub(r"\s+(?=\d{1,2}[.、)])", "\n", next_actions)

    profile = {
        "client_type": client_type,
        "core_demands": core_demands,
        "risks": _normalize_risks(_pick(data, "risks")),
        "communication": _text(_pick(data, "communication"), _LIMITS["communication"]),
        "next_actions": next_actions,
        "tags": _normalize_tags(_pick(data, "tags")),
        "evidence": _normalize_lines(_pick(data, "evidence"), _LIMITS["evidence"]),
        "gaps": _normalize_lines(_pick(data, "gaps"), _LIMITS["gap"]),
    }

    # 客户类型兜底：模型只给了核心诉求时，用标签/诉求补齐展示位
    if not profile["client_type"]:
        profile["client_type"] = "数据不足（档案未体现客户身份特征）"
    if not profile["core_demands"]:
        profile["core_demands"] = "数据不足（档案未体现明确诉求）"
    return profile
