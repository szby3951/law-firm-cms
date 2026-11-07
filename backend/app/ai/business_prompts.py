"""「AI督办」提示词：只读台账，盯进度与节点，不做法律咨询。

这个模块与 :mod:`app.ai.prompts`（AI 法律问答）是**两条互不相干的链路**，
分开的直接原因是两边的规矩互相冲突：

- 法律问答：只依据法条，每个结论标 ``[n]``，多说一句没有依据的话都是风险；
- AI督办：只依据台账，数字逐字照抄，**一句法条都不该出现**——用户来催
  「我还差多少钱」，不需要《民法典》第五百八十五条。

9.10 曾把两者塞进同一次请求，用关键词判意图切换模板。实测的问题不是"不准"，
而是两套规矩在一条系统提示词里互相稀释：问费用时模型仍会补一段收费规则，
问进度时仍会带出审限规定。拆成两个入口后，各自的提示词只需要讲一件事。

三条硬约束见 :data:`BUSINESS_RULES`，落点是「可核对」：回答里的每个数字都应
能在案件详情页或账单页找到同一个值。
"""

from __future__ import annotations

from app.ai.llm_clients.base import Message
from app.config import settings

__all__ = [
    "BUSINESS_RULES",
    "BUSINESS_SYSTEM_PROMPT",
    "build_business_messages",
    "render_business_context",
]

# 与法律问答的免责声明不同：这里查的是台账数据，风险在"数据过期"而不在
# "法律意见有误"。文案要指向核对，而不是指向"不构成法律意见"。
BUSINESS_DISCLAIMER = "数据来自律所业务系统实时读取，以案件与账单页面登记为准。"

BUSINESS_RULES = """
## 你的定位
你在律所业务系统里，替提问者盯着**本人权限范围内**的事项：案件办到哪一步、卡在哪个
环节、费用收了多少还差多少、哪些节点快到期。你的价值在「盯住」而不在「罗列」——
把该催的、该办的、快到期的挑出来。你不是法律顾问：同一个系统里另有「AI 法律问答」
负责解释法律条文，不要越界。

## 硬约束
1. **事实只来自【业务数据】。** 金额、案号、日期、期次、发票状态逐字取自该段，
   不要估算、不要用收费标准倒推、不要用行业惯例补齐。段里没有的项，写
   「系统未登记该信息」。
2. **不引法条、不标 [n]、不做法律分析。** 不要解释某条法律规定、不要评估胜诉
   可能、不要给诉讼策略。用户若明显在问法律依据，在回答末尾加一句：
   「法律依据可以在「AI 法律问答」里继续问。」只在末尾一句，不要展开。
3. **开头点明数据时点**，如「截至 {as_of}」，让用户知道这是快照而不是实时推送。
4. **先给结论数字，再给明细。** 「你要交的钱还差 ¥19,200」比先讲三段背景有用。
5. **时间是风险，要单独点出来**：已逾期、7 天内开庭、举证期限临期、合同 30 天
   内到期，逐项提示并说明"还剩几天"。
6. 数据只覆盖本人权限范围（客户=本人委托；律师=本人承办；管理员=全所）。问到不在
   范围内的案件，说明「不在你的权限范围或系统无记录」，不要猜。
7. 名下有多个在办案件而用户没指明是哪一个时，按在办优先逐条给出，末尾追问
   「你想重点看哪一件」。**不要**因为缺少某一项就说「现有资料未涵盖」，也不要为了
   凑结构补一段与问题无关的内容。
8. 回答用简体中文，像同事对账一样直白，不用"尊敬的用户"这类客套。
   涉及金额时保留两位小数与千分位，与台账一致。
9. **收尾给一条督办建议**：回答最后另起一句「接下来最该做的一件事：……」，只给
   一条，具体到「谁做什么」。**日期只能取自【业务数据】里已登记的期限**（开庭日、
   应缴日、举证期限、合同到期日）；数据里没有期限时写「尽快」，不要自己按"7 天内"
   "本周内"推算出一个具体日期——写出来的日期用户会当成台账事实。没有可催办的事项
   就不写这句，不要为了凑格式编一条。
"""

BUSINESS_CLIENT_EXTRA = """
## 面向当事人（非法律专业人士）
- 用日常语言说，不要出现"标的额"「案由」这类术语；必须用时用括号解释。
- 不预测结果、不评价律师办案质量、不承诺胜诉。
- 只披露本人的费用：应收、已缴、待缴、逾期。律所成本、其他客户信息一律不提。
- 涉及缴费、开庭时间时，同时说明"该做什么"，例如"可在「我的账单」页在线缴纳"。
"""

BUSINESS_SYSTEM_PROMPT = """你是「{firm}」业务系统的督办助手，负责根据实时业务台账盯住
提问者本人的案件进度、费用缴纳、日程与合同到期情况。{rules}"""

_USER_TEMPLATE = """{business}

【问题】
{question}

请只依据上面的业务数据作答：数字逐字照抄，缺项写「系统未登记该信息」，
不要引法条、不要标注引用编号、不要做法律分析。"""


def build_system_prompt(role: str = "lawyer", *, as_of: str = "") -> str:
    """业务助理的系统提示词。客户侧额外加一段通俗化要求。

    ``as_of`` 只用于规则里的「截至 {as_of}」示例，让模型知道该把哪个时间写进
    回答开头——数据本身的时间在【业务数据】标题里也有一份。
    """
    rules = BUSINESS_RULES.format(as_of=as_of or "当前时间")
    prompt = BUSINESS_SYSTEM_PROMPT.format(firm=settings.firm_name, rules=rules)
    if role == "client":
        prompt += BUSINESS_CLIENT_EXTRA
    return prompt


def build_business_messages(
    question: str,
    business_context: str,
    *,
    as_of: str,
    history: list[Message] | None = None,
    role: str = "lawyer",
) -> list[Message]:
    """组装消息：system（含数据时点）→ 历史 → 业务数据 + 问题。

    历史沿用 :func:`app.services.ai_service._load_history` 的结果（已脱敏、
    已剥掉旧的 ``[n]``）。业务数据每轮重新取，历史里不保留旧金额——上一轮的
    「还差 19200」到了这一轮可能已经收了一笔，模型不该拿旧数字凑答案。
    """
    system = build_system_prompt(role, as_of=as_of)
    messages: list[Message] = [{"role": "system", "content": system}]
    if history:
        messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                business=business_context, question=question.strip()
            ),
        }
    )
    return messages


def render_business_context(
    *,
    as_of: str,
    blocks: list[tuple[str, list[str]]],
    max_chars: int,
) -> tuple[str, bool]:
    """把分节内容拼成一段文本，超出预算时整块丢弃而不是切断半条记录。

    :param as_of: 快照时间，写进标题，回答里要能引用
    :param blocks: ``[(小节标题, [行, ...]), ...]``，空行列表会被跳过
    :param max_chars: 字符预算（不含标题）
    :return: ``(文本, 是否截断)``

    按整块裁剪的原因：一条案件由"基本情况 + 下次开庭"两行组成，切一半会让模型
    拿着半个日期作答，比不给更危险。
    """
    head = f"【业务数据｜查询时间 {as_of}｜来源：律所业务系统实时读取】"
    parts: list[str] = [head]
    used = 0
    truncated = False

    for title, lines in blocks:
        rows = [line for line in lines if line]
        if not rows:
            continue
        chunk = "\n".join([title, *rows]) if title else "\n".join(rows)
        if used + len(chunk) > max_chars:
            truncated = True
            continue
        parts.append(chunk)
        used += len(chunk) + 1

    if truncated:
        parts.append(
            "（篇幅所限，其余条目已省略；如问题涉及未列出的记录，请说明案号或合同名）"
        )
    return "\n".join(parts), truncated
