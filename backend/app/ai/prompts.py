"""提示词模板（任务拆解 9.3.2）。

RAG 问答的效果有一半取决于提示词。这里的写法针对三件事：

**1. 抑制幻觉**
明确「只依据参考资料」「资料不足时直接说明」，并禁止编造法条、案号、判例、
数字。法律场景里一本正经的错答比"不知道"危险得多——用户会拿它去写文书。

**2. 强制可溯源**
要求在每个结论句末标 ``[n]``，编号只能来自【参考资料】。前端据此做点击展开
原文（9.8.2），也是本项目"可审计"的落点。

**3. 区分律师与客户**
律师要的是结论 + 依据 + 操作路径；客户需要通俗解释、不许胜诉承诺。两者共用
同一份检索结果，只在系统提示词上追加一段（``CLIENT_EXTRA``）。

唯一的要求是**不要**在提示词里写"请务必引用"——检索为空时模型会为了满足指令
而虚构编号。这里改成"资料不足就说明"，让模型有正当的拒答出口。
"""

from __future__ import annotations

import re

from app.ai.llm_clients.base import Message
from app.ai.rag import Reference, format_context
from app.config import settings

__all__ = [
    "DISCLAIMER",
    "build_chat_messages",
    "build_system_prompt",
    "extract_used_refs",
]

# 合规兜底文案（9.9.1）。不拼进回答正文，由接口在 done 事件与历史接口里单独返回，
# 前端固定渲染在气泡底部——这样免责声明不会混进上下文，也不会被模型改写。
DISCLAIMER = "本内容仅供参考，不构成法律意见。"

_SYSTEM_PROMPT = """你是「{firm}」的资深法律顾问，为中国大陆的律师与当事人提供法律咨询。

## 回答规则
1. **只依据【参考资料】作答。** 资料不足以支撑结论时，直接说明「现有资料未涵盖该问题」，
   并给出可执行的下一步（需要补充哪类材料、应咨询哪类专业律师），
   不得编造法条、案号、判例、金额或期限。
2. 引用资料时在相应句末标注编号，如 [1]、[2]。编号必须来自【参考资料】，
   不得虚构，也不要给同一段资料编两个号。
3. 引用法律条文时写明法律名称与条号，如《中华人民共和国民法典》第五百八十五条。
4. 回答结构：**先给结论**，再列法律依据，最后给操作建议；分点表述，避免大段堆砌。
5. 涉及金额、比例、期限时说明计算口径或区间；没有依据时不要给出确定数字。
6. 不得提供伪造证据、隐匿转移财产、规避法律监管等违法建议。
7. 使用简体中文。不要在正文结尾重复免责声明，系统会统一附加。
8. 如果问题要的是**某个具体案件的进度、本人的缴费情况、开庭时间**这类系统里的
   记录：只用一句话说明本入口只解答法律问题、请到「AI督办」查询，然后结束。
   不要接着补通用办案流程、审限规定或法条分析——用户要的是他那件案子的状态，
   通用规定对他没有帮助，长篇输出反而掩盖了那句引导。
"""

_CLIENT_EXTRA = """
## 面向当事人（非法律专业人士）的额外要求
- 用通俗语言解释，必须使用法律术语时用括号说明含义。
- 不做胜诉承诺，不预测具体判决结果或赔偿金额。
- 涉及诉讼时效、举证期限、上诉期等时间节点时，提醒尽快联系承办律师，逾期可能丧失权利。
- 不提供诉讼策略、谈判底牌等只适合律师内部讨论的内容。
"""

_USER_TEMPLATE = """【参考资料】
{context}

【问题】
{question}

请严格依据上述参考资料回答。引用处标注 [n]，编号与参考资料一致；
资料不足时如实说明，不要补充参考资料之外的法条或案例。"""


def build_system_prompt(role: str = "lawyer") -> str:
    """按角色拼系统提示词。``role`` 取 ``client`` 时追加当事人约束。"""
    prompt = _SYSTEM_PROMPT.format(firm=settings.firm_name)
    if role == "client":
        prompt += _CLIENT_EXTRA
    return prompt


def build_chat_messages(
    question: str,
    refs: list[Reference],
    *,
    history: list[Message] | None = None,
    role: str = "lawyer",
) -> list[Message]:
    """组装完整消息列表：system → 历史 → 本轮（资料 + 问题）。

    :param question: 已脱敏的问题
    :param refs: 检索到的引用，编号与 :func:`app.ai.rag.retrieve` 一致
    :param history: 之前的多轮消息（已脱敏、已去掉旧编号，见 ai_service）

    这里只拼**法条**。本人案件与费用走另一条链路
    （:mod:`app.ai.business_prompts`），不要把业务数据混进来——两套来源的
    可信度基准不同，混在一条消息里模型会拿台账数字去凑法条结论。
    """
    messages: list[Message] = [
        {"role": "system", "content": build_system_prompt(role)}
    ]
    if history:
        messages.extend(history)
    messages.append(
        {
            "role": "user",
            "content": _USER_TEMPLATE.format(
                context=format_context(refs), question=question.strip()
            ),
        }
    )
    return messages


def extract_used_refs(answer: str, ref_count: int) -> list[int]:
    """从回答中解析实际被引用的编号，返回升序去重后的列表。

    模型常把 ``[1]`` 写成 ``【1】``，也会出现 ``[1][2]`` 连写；两种括号都认。
    越界编号（模型自己编的）直接丢弃，不提示用户——提示反而会让用户以为
    那条法条存在过。
    """
    if not answer or ref_count <= 0:
        return []
    found = {
        int(num)
        for num in re.findall(r"[\[【]\s*(\d{1,2})\s*[\]】]", answer)
        if 1 <= int(num) <= ref_count
    }
    return sorted(found)
