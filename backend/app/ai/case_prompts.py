"""案件摘要提示词（任务拆解 9.6.1）。

案件摘要与前面三类 AI 能力的区别在于**输出是给人快速读完的**：律师打开卷宗
之前先看这一页，就知道这是什么案子、争什么、手上有什么、下一步做什么。因此
提示词不追求"全面复述"，而是强制做三件事：

1. **固定结构**：六个小节（概况 / 争议焦点 / 事实与证据 / 有利不利 / 下一步 /
   材料缺口）写成硬约束。自由发挥的摘要每次结构都不同，交接时反而要重新翻材料。
2. **事实与判断分离**：材料载明的内容直接写；模型自己的判断必须加「初步判断：」
   并说明依据，不确定的标「待核实」。摘要一旦把推测写成事实，下一手律师会当真。
3. **出处与缺口**：每个事实尽量带材料名/日期/条款号；没写的写「材料未载明」，
   而不是留空或补全。材料缺口单独成节——它往往比已有内容更能指导下一步取证。

摘要不做脱敏：它是律师内部工作底稿，当事人姓名、金额、案号必须原样保留，
否则无法与卷宗对应；权限由「仅承办律师/管理员可触发」控制（架构文档 6.5）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.ai.llm_clients.base import Message
from app.config import settings

__all__ = [
    "DISCLAIMER",
    "SECTIONS",
    "SummarySection",
    "build_case_summary_messages",
    "build_system_prompt",
]

DISCLAIMER = (
    "AI 案件摘要由案件档案与案卷材料自动归纳，可能存在遗漏或误读，"
    "仅供承办律师内部参考，不构成法律意见；引用前请核对原始材料。"
)


@dataclass(frozen=True, slots=True)
class SummarySection:
    """摘要的一个固定小节。

    :param key: 英文标识，便于前端按节折叠（当前直接渲染 Markdown，暂未使用）
    :param title: 中文标题，含序号
    :param requirement: 这一节必须写什么、写到什么粒度
    """

    key: str
    title: str
    requirement: str


# 顺序即输出顺序。标题里的序号写死，避免模型自己编号时从「一」跳到「三」。
SECTIONS: tuple[SummarySection, ...] = (
    SummarySection(
        "overview",
        "一、案件概况",
        "先用 2~3 句说明案件性质与当前进展；再用短列表列出案号、案由、"
        "委托方与相对方、标的额、受理法院/机构、承办律师、立案与结案时间。",
    ),
    SummarySection(
        "disputes",
        "二、争议焦点",
        "按对处理结果的影响排序列出 1~4 个争议焦点；每个焦点写明双方各自主张"
        "及材料依据；只有一方主张时注明「对方主张材料未载明」。",
    ),
    SummarySection(
        "facts",
        "三、事实与证据",
        "按时间顺序列 5~12 个关键节点，格式为「日期｜事件｜出处」；随后单列证据："
        "证据名称、来源、待证事实。没有证据材料时写「材料未载明」，不要编造证据名。",
    ),
    SummarySection(
        "analysis",
        "四、有利与不利",
        "分「有利因素」「不利因素」「待核实事项」三组，只写材料能支撑的判断；"
        "每条注明依据，属于推断的加「初步判断：」；无法确认的标「待核实」。",
    ),
    SummarySection(
        "next_steps",
        "五、下一步与期限",
        "列 3~6 项下一步工作，写清做什么、对应时间节点；日期只引用档案、日程或"
        "材料中出现的，没有登记就写「档案未登记期限」。同时提示材料中已出现的"
        "举证期限、上诉期、诉讼时效等期限风险。",
    ),
    SummarySection(
        "gaps",
        "六、材料缺口",
        "按对办案的影响从大到小，列出缺失的关键材料或信息，并说明缺了会影响"
        "哪项判断；没有明显缺口时写「暂未发现关键材料缺口」。",
    ),
)


def build_system_prompt() -> str:
    """系统提示词：角色 + 七条硬规则 + 输出格式 + 六节要求。"""
    sections = "\n\n".join(
        f"## {section.title}\n{section.requirement}" for section in SECTIONS
    )
    return f"""你是「{settings.firm_name}」的案件管理助手，负责把分散在案件档案、\
时间线和案卷材料里的信息压缩成一份可直接用于交接、庭前准备与复盘的内部摘要。

【必须遵守】
1. 只使用给定材料中的信息。材料没有写的，一律写「材料未载明」；不得凭常识补全
   当事人关系、金额、日期、证据或法律依据。
2. 材料之间互相矛盾时并列写明（例如「《起诉状》称……，《答辩状》称……」），
   不要替律师取舍，也不要只采用其中一份。
3. 每个事实性表述尽量带出处（材料名；有条款号、日期、页码的写上），方便回查。
4. 把「材料载明的事实」与「你的判断」分开：判断前加「初步判断：」并说明依据；
   无法确认的标「待核实」。
5. 金额、日期、案号、人名原样引用，不做换算、不四舍五入、不推断缺失位数。
6. 不预测裁判结果，不写胜诉率，不引用材料之外的法条。
7. 语言简洁、句子短；不写开场白、客套话和总结段，直接从「一句话概要」开始。

【输出格式】
- 使用 Markdown。
- 第一行固定为 `> 一句话概要：……`（不超过 80 字，说清谁与谁、因何事、
  处于什么阶段）。
- 然后严格按下列六个小节输出，标题格式为 `## 一、案件概况`……；小节不得增删、
  不得改名、不得调序。
- 某节确实没有材料支撑时，保留标题并写「材料未载明」，不要留空。
- 列表用 `- `；需要强调的内容用 `**粗体**`；不要使用表格。

【六个小节】
{sections}
"""


def _count(value: int) -> str:
    return f"{value:,}"


def _material_block(index: int, material: dict[str, Any]) -> str:
    """一份材料的正文块。

    标题里带类型、原名、原始字数与是否节选：模型需要知道"这份材料被截过"，
    否则会把节选当成全文，在摘要里写「材料至此结束」之类的错误结论。
    """
    title = str(material.get("title") or "未命名材料")
    kind_label = str(material.get("kind_label") or "材料")
    chars = int(material.get("chars") or 0)
    flags = []
    if material.get("truncated"):
        flags.append("已节选")
    if material.get("note"):
        flags.append(str(material["note"]))
    suffix = f"｜{'｜'.join(flags)}" if flags else ""
    text = str(material.get("text") or "").strip()
    return (
        f"--- 材料 {index}｜{kind_label}《{title}》｜{_count(chars)} 字{suffix} ---\n"
        f"{text}"
    )


def build_case_summary_messages(
    *,
    meta: dict[str, str],
    timeline: list[str],
    schedules: list[str],
    materials: list[dict[str, Any]],
    skipped: list[str],
    focus: str | None = None,
) -> list[Message]:
    """拼装案件摘要的对话消息。

    :param meta: 案件档案键值对（中文键，按插入顺序输出）
    :param timeline: 已格式化的时间线，一条一个节点
    :param schedules: 已格式化的待办/逾期日程
    :param materials: ``{kind_label,title,text,chars,truncated,note}``
    :param skipped: 因容量或格式未纳入的材料说明
    :param focus: 律师本次特别关注点
    """
    lines: list[str] = ["【案件档案】"]
    lines.extend(f"- {key}：{value}" for key, value in meta.items() if value)
    if len(lines) == 1:
        lines.append("（档案未填写基本信息）")

    lines.append("")
    lines.append("【案件时间线】")
    if timeline:
        lines.extend(f"{index}. {item}" for index, item in enumerate(timeline, 1))
    else:
        lines.append("（档案未登记时间线节点）")

    lines.append("")
    lines.append("【日程与期限】")
    if schedules:
        lines.extend(f"- {item}" for item in schedules)
    else:
        lines.append("（无待办或逾期日程）")

    lines.append("")
    lines.append("【案卷材料】")
    if materials:
        for index, material in enumerate(materials, 1):
            lines.append(_material_block(index, material))
            lines.append("")
    else:
        lines.append("（没有可读取的案卷材料，仅依据案件档案与时间线归纳）")

    if skipped:
        lines.append("【未纳入本次摘要的材料】")
        lines.extend(f"- {item}" for item in skipped)
        lines.append("")

    if focus:
        lines.append("【本次关注点】")
        lines.append(focus.strip())
        lines.append("")

    lines.append(
        "请按系统要求输出案件摘要。再次提醒：材料未载明的内容写「材料未载明」，"
        "不要补全或推测。"
    )

    return [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": "\n".join(lines).strip()},
    ]
