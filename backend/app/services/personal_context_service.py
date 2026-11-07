"""本人业务数据快照：「AI督办」模块的唯一数据来源。

模型看不到数据库。凡是「我的案件办到哪了」「我还差多少钱」这类问题，必须先
把提问者权限范围内的案件、费用、日程、合同读成一段纯文本，再随问题送进模型。
本模块只负责取数与格式化，不判断"该不该注入"——调用的入口只有一个
（``POST /api/business/chat``），每次都要注入，没有开关。

四条设计约束：

- **权限与页面一致**：客户走 ``list_my_cases`` / ``list_my_bills``，律师走
  ``list_cases`` / ``list_collect_list`` / ``list_upcoming``，复用既有 service。
  不另写一套范围判定，否则迟早出现"AI 能看到的比页面多"。
- **只传值类型**：返回 ``PersonalContext``，不持有 ORM 对象——生成器跑在响应
  阶段，与请求级会话生命周期不一致，传对象会踩到"会话已关闭"。
- **脱敏后再出站**：自然人姓名只留姓（``张*``），机构名保留；身份证、手机号、
  详细地址一律不进入上下文。金额对客户只出应收/已缴/待缴，不出成本与利润。
- **失败不阻塞**：取数出异常只记日志并返回空上下文，服务层据此告诉用户
  「业务数据暂时读不到」，而不是编一份出来。

预算是硬性的：一段上下文最多 :data:`PERSONAL_CONTEXT_MAX_CHARS` 字，超出的
整块丢弃（见 :func:`app.ai.business_prompts.render_business_context`）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai import business_prompts
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.schedule import Schedule
from app.models.user import User
from app.services import (
    billing_service,
    case_service,
    contract_service,
    schedule_service,
)

__all__ = [
    "PERSONAL_CONTEXT_MAX_CHARS",
    "PersonalContext",
    "build_business_snapshot",
]

logger = logging.getLogger(__name__)

# 2200 字约 1500 token，相当于把 8 个案件、8 笔待收、6 条日程讲清楚；
# 再往上加，法条与历史对话的预算就会被挤掉。
PERSONAL_CONTEXT_MAX_CHARS = 2200
PERSONAL_CONTEXT_MAX_CASES = 8
PERSONAL_CONTEXT_MAX_BILLS = 8
PERSONAL_CONTEXT_MAX_SCHEDULES = 6
PERSONAL_CONTEXT_MAX_CONTRACTS = 5

ZERO = Decimal("0.00")

CASE_STATUS_LABELS = {
    "consulting": "咨询中",
    "filed": "已立案",
    "handling": "办理中",
    "pending_close": "待结案",
    "closed": "已结案",
    "withdrawn": "已退案",
}
FEE_TYPE_LABELS = {
    "fixed": "固定收费",
    "ratio": "按标的比例",
    "risk": "风险代理",
    "hourly": "计时收费",
}
PERIOD_STATUS_LABELS = {"unpaid": "未收", "partial": "部分收款", "paid": "已结清"}
INVOICE_LABELS = {"none": "未开具", "applied": "申请中", "issued": "已开具"}
CONTRACT_STATUS_LABELS = {
    "draft": "草稿",
    "active": "生效中",
    "expired": "已到期",
    "terminated": "已终止",
}
SCHEDULE_TYPE_LABELS = {
    "hearing": "开庭",
    "deadline": "期限",
    "visit": "回访",
    "meeting": "会议",
}
DUTY_LABELS = {"lead": "主办", "assist": "协办"}

# 机构名里出现这些词就不打码——公司名是律师识别案件的关键，打码等于废掉上下文
_COMPANY_HINTS = (
    "公司",
    "事务所",
    "银行",
    "中心",
    "集团",
    "医院",
    "学校",
    "大学",
    "研究院",
    "协会",
    "商会",
    "政府",
    "委员会",
    "工作室",
    "工厂",
    "厂",
    "店",
    "合作社",
    "机构",
)


@dataclass(slots=True)
class PersonalContext:
    """一次业务问答可用的本人业务快照。``text`` 为空表示取数失败。"""

    scope: str
    as_of: str
    text: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    truncated: bool = False

    @property
    def ok(self) -> bool:
        return bool(self.text)

    @property
    def chars(self) -> int:
        return len(self.text)


# ---------------------------------------------------------------------------
# 格式化小工具
# ---------------------------------------------------------------------------


def _money(value: Any) -> str:
    if value is None:
        return "未登记"
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return "未登记"
    return f"¥{amount:,.2f}"


def _dec(value: Any) -> Decimal:
    if value is None:
        return ZERO
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (ArithmeticError, ValueError):
        return ZERO


def _day(value: date | datetime | None) -> str:
    if value is None:
        return "未登记"
    return value.strftime("%Y-%m-%d")


def _moment(value: datetime | None) -> str:
    if value is None:
        return "未登记"
    return value.strftime("%Y-%m-%d %H:%M")


def _is_company(name: str | None) -> bool:
    return bool(name) and any(hint in name for hint in _COMPANY_HINTS)


def _mask_name(name: str | None) -> str:
    """自然人只留姓；机构名原样返回。"""
    if not name:
        return "未登记"
    if _is_company(name) or len(name) <= 1:
        return name
    return name[0] + "*" * (len(name) - 1)


def _mask_title(title: str | None, aliases: list[str]) -> str:
    """把案件标题里的当事人真名换成掩码，机构名保留。

    只替换"已知姓名"而不是跑通用姓名识别：案件标题常常没有"当事人"这类提示词，
    正则认不出来；而客户名、对方当事人名是手里现成的，整词替换最稳。
    """
    text = title or "未登记"
    for name in aliases:
        if name and not _is_company(name) and len(name) > 1 and name in text:
            text = text.replace(name, _mask_name(name))
    return text


def _link(role: str, suffix: str) -> str:
    prefix = {"client": "/client", "admin": "/admin"}.get(role, "/lawyer")
    return f"{prefix}{suffix}"


# ---------------------------------------------------------------------------
# 取数：客户视角
# ---------------------------------------------------------------------------


async def _client_blocks(
    db: AsyncSession, current: User
) -> tuple[list[tuple[str, list[str]]], list[dict[str, Any]], dict[str, int]]:
    """客户：本人委托的案件 + 账单 + 合同 + 开庭安排。"""
    cases = await case_service.list_my_cases(db, current)
    bills = await billing_service.list_my_bills(db, current)
    contracts = await contract_service.list_my_contracts(db, current)

    case_ids = [c.id for c in cases]
    hearings: list[Schedule] = []
    if case_ids:
        rows = (
            await db.execute(
                select(Schedule)
                .where(
                    Schedule.case_id.in_(case_ids),
                    Schedule.status == "pending",
                    Schedule.event_date >= datetime.now(),
                    Schedule.schedule_type.in_(("hearing", "deadline")),
                )
                .order_by(Schedule.event_date.asc())
                .limit(PERSONAL_CONTEXT_MAX_SCHEDULES)
            )
        ).scalars()
        hearings = list(rows)

    hearing_map: dict[int, Schedule] = {}
    for row in hearings:
        if row.case_id is not None:
            hearing_map.setdefault(row.case_id, row)

    status_count: dict[str, int] = {}
    for c in cases:
        status_count[c.status] = status_count.get(c.status, 0) + 1
    status_text = "、".join(
        f"{CASE_STATUS_LABELS.get(k, k)} {v} 件" for k, v in status_count.items()
    )

    # 客户自己的姓名与对方当事人名，用于标题打码
    client = None
    if cases:
        client = await db.get(ClientProfile, cases[0].client_id)

    items: list[dict[str, Any]] = []
    case_lines: list[str] = []
    shown = cases[:PERSONAL_CONTEXT_MAX_CASES]
    for idx, c in enumerate(shown, start=1):
        aliases = [client.name if client else None, c.opposing_party]
        title = _mask_title(c.title, [a for a in aliases if a])
        bits = [f"{idx}. {title}", f"案号 {c.case_no}"]
        bits.append(f"状态 {CASE_STATUS_LABELS.get(c.status, c.status)}")
        if c.case_cause:
            bits.append(f"案由 {c.case_cause}")
        if c.court:
            bits.append(f"法院/机构 {c.court}")
        if c.amount:
            bits.append(f"标的额 {_money(c.amount)}")
        case_lines.append("｜".join(bits))
        hearing = hearing_map.get(c.id)
        if hearing:
            case_lines.append(
                f"   下次安排：{_moment(hearing.event_date)}"
                f" {SCHEDULE_TYPE_LABELS.get(hearing.schedule_type, hearing.schedule_type)}"
                f"｜{hearing.title}"
            )
        items.append(
            {
                "kind": "case",
                "label": f"{c.case_no} {title}",
                "detail": CASE_STATUS_LABELS.get(c.status, c.status),
                "link": _link("client", f"/cases/{c.id}"),
            }
        )

    blocks: list[tuple[str, list[str]]] = [
        (
            "",
            [
                (
                    f"登录人：{current.real_name or current.username}（当事人本人）"
                    "｜数据范围：本人委托的案件、账单与合同"
                )
            ],
        ),
        (
            f"一、我的案件（共 {len(cases)} 件"
            + (f"：{status_text}" if status_text else "")
            + "）",
            case_lines,
        ),
    ]

    total_due = sum((_dec(b.due_amount) for b in bills), ZERO)
    total_paid = sum((_dec(b.paid_amount) for b in bills), ZERO)
    total_unpaid = total_due - total_paid
    overdue = [b for b in bills if b.status != "paid" and (b.overdue_days or 0) > 0]

    fee_lines = [
        (
            f"应缴合计 {_money(total_due)}｜已缴 {_money(total_paid)}"
            f"｜待缴 {_money(total_unpaid)}"
        )
    ]
    if overdue:
        fee_lines.append(
            f"其中已逾期 {len(overdue)} 笔，合计 "
            f"{_money(sum((_dec(b.unpaid_amount) for b in overdue), ZERO))}"
        )
    pending = [b for b in bills if b.status != "paid"]
    for b in pending[:PERSONAL_CONTEXT_MAX_BILLS]:
        line = (
            f"- {b.case_title}｜第 {b.period_no} 期"
            f"｜应缴 {_money(b.due_amount)}｜已缴 {_money(b.paid_amount)}"
            f"｜待缴 {_money(b.unpaid_amount)}"
            f"｜应缴日期 {_day(b.due_date)}"
            f"｜{PERIOD_STATUS_LABELS.get(b.status, b.status)}"
            f"｜发票 {INVOICE_LABELS.get(b.invoice_status, b.invoice_status)}"
        )
        if b.overdue_days:
            line += f"｜已逾期 {b.overdue_days} 天"
        fee_lines.append(line)
        items.append(
            {
                "kind": "fee",
                "label": f"{b.case_title} 第 {b.period_no} 期",
                "detail": f"待缴 {_money(b.unpaid_amount)}",
                "link": _link("client", "/bills"),
            }
        )
    if not bills:
        fee_lines.append("- 系统未登记收费方案")
    blocks.append(("二、我的费用（截至今日）", fee_lines))

    if hearings:
        rows = [
            f"- {_moment(h.event_date)}"
            f"｜{SCHEDULE_TYPE_LABELS.get(h.schedule_type, h.schedule_type)}"
            f"｜{h.title}"
            for h in hearings
        ]
        blocks.append(("三、近期开庭与期限", rows))

    contract_lines: list[str] = []
    active = [c for c in contracts if c.status == "active"]
    today = date.today()
    expiring = [
        c for c in active if c.end_date and 0 <= (c.end_date - today).days <= 30
    ]
    if contracts:
        contract_lines.append(
            f"共 {len(contracts)} 份，生效中 {len(active)} 份"
            + (f"，30 天内到期 {len(expiring)} 份" if expiring else "")
        )
        for c in contracts[:PERSONAL_CONTEXT_MAX_CONTRACTS]:
            line = (
                f"- {c.name}｜{CONTRACT_STATUS_LABELS.get(c.status, c.status)}"
                f"｜金额 {_money(c.amount)}"
                f"｜起 {_day(c.start_date)} 止 {_day(c.end_date)}"
            )
            contract_lines.append(line)
            items.append(
                {
                    "kind": "contract",
                    "label": c.name,
                    "detail": CONTRACT_STATUS_LABELS.get(c.status, c.status),
                    "link": _link("client", f"/contracts/{c.id}"),
                }
            )
    else:
        contract_lines.append("系统未登记合同")
    blocks.append(("四、我的合同", contract_lines))

    counts = {
        "cases": len(cases),
        "bills": len(bills),
        "pending_bills": len(pending),
        "contracts": len(contracts),
        "schedules": len(hearings),
    }

    return blocks, items, counts


# ---------------------------------------------------------------------------
# 取数：律师 / 管理员视角
# ---------------------------------------------------------------------------


async def _case_lawyer_map(
    db: AsyncSession, case_ids: list[int], self_id: int | None = None
) -> dict[int, list[str]]:
    """案件 → 承办律师（含主办/协办），一次查完避免 N+1。

    登录人本人显示真名：他看的就是自己的名字，打码只会让模型写出
    「您（古***律师）」这种怪句子。其他律师与客户仍然打码。
    """
    if not case_ids:
        return {}
    rows = (
        await db.execute(
            select(
                CaseLawyer.case_id,
                CaseLawyer.duty,
                CaseLawyer.lawyer_id,
                User.real_name,
            )
            .join(User, User.id == CaseLawyer.lawyer_id)
            .where(CaseLawyer.case_id.in_(case_ids))
        )
    ).all()
    result: dict[int, list[str]] = {}
    for case_id, duty, lawyer_id, name in rows:
        is_self = self_id is not None and lawyer_id == self_id
        shown = name if is_self else _mask_name(name)
        tag = DUTY_LABELS.get(duty, duty) + ("·本人" if is_self else "")
        result.setdefault(case_id, []).append(f"{shown}（{tag}）")
    return result


async def _staff_blocks(
    db: AsyncSession, current: User
) -> tuple[list[tuple[str, list[str]]], list[dict[str, Any]], dict[str, int]]:
    """律师/管理员：承办案件 + 收费概览与催收 + 日程 + 合同。"""
    total, cases = await case_service.list_cases(db, current=current, page_size=100)
    stats = await billing_service.get_billing_stats(db, current)
    # 按方案（≈按案件）的收费明细：只给汇总的话，模型答"未拆分到单案"就没用了
    _, plans = await billing_service.list_fee_plans(
        db, current=current, page_size=50
    )
    plans = [p for p in plans if _dec(p.due_total) > 0]
    plans.sort(key=lambda p: _dec(p.due_total) - _dec(p.paid_total), reverse=True)
    collects = await billing_service.list_collect_list(db, current)
    today_schedules = await schedule_service.list_today(db, current)
    upcoming = await schedule_service.list_upcoming(db, current, days=7)
    _, contracts = await contract_service.list_contracts(
        db, current=current, page_size=50
    )

    scope_label = "全所" if current.role == "admin" else "本人承办"
    status_count: dict[str, int] = {}
    for c in cases:
        status_count[c.status] = status_count.get(c.status, 0) + 1
    status_text = "、".join(
        f"{CASE_STATUS_LABELS.get(k, k)} {v} 件" for k, v in status_count.items()
    )

    # 未结案优先展示，已结案的排在后面：用户问"办到哪了"关心的是在办的
    ordered = sorted(
        cases,
        key=lambda c: (c.status in ("closed", "withdrawn"), -c.id),
    )
    shown = ordered[:PERSONAL_CONTEXT_MAX_CASES]
    lawyers_map = await _case_lawyer_map(db, [c.id for c in shown], current.id)

    # 客户姓名一次查完：逐条 db.get 会退化成 N+1
    client_ids = [c.client_id for c in shown if c.client_id]
    client_names: dict[int, str] = {}
    if client_ids:
        rows = (
            await db.execute(
                select(ClientProfile.id, ClientProfile.name).where(
                    ClientProfile.id.in_(client_ids)
                )
            )
        ).all()
        client_names = {cid: name for cid, name in rows}

    # 日程按案件归并，用于"下一节点"
    next_map: dict[int, Schedule] = {}
    for s in [*today_schedules, *upcoming]:
        if s.case_id is not None and s.status == "pending":
            next_map.setdefault(s.case_id, s)

    items: list[dict[str, Any]] = []
    case_lines: list[str] = []
    for idx, c in enumerate(shown, start=1):
        client_name = client_names.get(c.client_id) if c.client_id else None
        title = _mask_title(
            c.title,
            [n for n in (client_name, c.opposing_party) if n],
        )
        bits = [f"{idx}. {title}"]
        bits.append(f"案号 {c.case_no}")
        bits.append(f"状态 {CASE_STATUS_LABELS.get(c.status, c.status)}")
        if c.case_cause:
            bits.append(f"案由 {c.case_cause}")
        if c.court:
            bits.append(f"法院 {c.court}")
        if c.amount:
            bits.append(f"标的额 {_money(c.amount)}")
        if client_name:
            bits.append(f"客户 {_mask_name(client_name)}")
        duty = lawyers_map.get(c.id)
        if duty:
            bits.append(f"承办 {'、'.join(duty)}")
        if c.status in ("closed", "withdrawn") and c.closed_at:
            bits.append(f"结案 {_day(c.closed_at)}")
        case_lines.append("｜".join(bits))
        node = next_map.get(c.id)
        if node:
            case_lines.append(
                f"   下一节点：{_moment(node.event_date)}"
                f" {SCHEDULE_TYPE_LABELS.get(node.schedule_type, node.schedule_type)}"
                f"｜{node.title}"
            )
        items.append(
            {
                "kind": "case",
                "label": f"{c.case_no} {title}",
                "detail": CASE_STATUS_LABELS.get(c.status, c.status),
                "link": _link(current.role, f"/cases/{c.id}"),
            }
        )

    more = "（仅列最近若干件）" if total > len(shown) else ""
    role_label = "管理员" if current.role == "admin" else "承办律师"
    blocks: list[tuple[str, list[str]]] = [
        (
            "",
            [
                (
                    f"登录人：{current.real_name or current.username}（{role_label}）"
                    f"｜数据范围：{scope_label}案件"
                )
            ],
        ),
        (
            f"一、{scope_label}的案件（共 {total} 件"
            + (f"：{status_text}" if status_text else "")
            + f"）{more}",
            case_lines,
        ),
    ]

    fee_lines = [
        (
            f"应收合计 {_money(stats.total_due)}｜已收 {_money(stats.total_paid)}"
            f"｜未收 {_money(stats.total_unpaid)}"
            f"｜回款率 {stats.collection_rate}%"
            f"｜逾期 {stats.overdue_count} 笔共 {_money(stats.overdue_amount)}"
        )
    ]
    for p in plans[:PERSONAL_CONTEXT_MAX_BILLS]:
        unpaid = _dec(p.due_total) - _dec(p.paid_total)
        fee_lines.append(
            f"- {p.case_title or '未关联案件'}"
            f"（客户 {_mask_name(p.client_name)}）"
            f"｜{FEE_TYPE_LABELS.get(p.fee_type, p.fee_type)}"
            f"｜收费总额 {_money(p.total_amount)}"
            f"｜应收 {_money(p.due_total)}｜已收 {_money(p.paid_total)}"
            f"｜未收 {_money(unpaid)}｜分 {p.period_count} 期"
        )
        items.append(
            {
                "kind": "fee",
                "label": f"{p.case_title or '收费方案'} 费用",
                "detail": f"未收 {_money(unpaid)}",
                "link": _link(current.role, f"/billing/{p.id}"),
            }
        )
    if not plans:
        fee_lines.append("- 系统未登记收费方案")

    if collects:
        fee_lines.append("已到期未结清：")
        for item in collects[:PERSONAL_CONTEXT_MAX_BILLS]:
            fee_lines.append(
                f"- {item.case_title}（{_mask_name(item.client_name)}）"
                f"｜第 {item.period_no} 期"
                f"｜应收 {_money(item.due_amount)}｜已收 {_money(item.paid_amount)}"
                f"｜未收 {_money(item.unpaid_amount)}"
                f"｜到期 {_day(item.due_date)}"
                f"（逾期 {item.overdue_days} 天）"
            )
            items.append(
                {
                    "kind": "fee",
                    "label": f"{item.case_title} 第 {item.period_no} 期",
                    "detail": f"未收 {_money(item.unpaid_amount)}",
                    "link": _link(current.role, "/billing/collect"),
                }
            )
    blocks.append(("二、收费与催收（截至今日）", fee_lines))

    schedule_lines: list[str] = []
    if today_schedules:
        schedule_lines.append(
            "今日："
            + "；".join(
                f"{s.event_date.strftime('%H:%M')}"
                f" {SCHEDULE_TYPE_LABELS.get(s.schedule_type, s.schedule_type)}"
                f" {s.title}"
                for s in today_schedules[:4]
            )
        )
    if upcoming:
        schedule_lines.extend(
            f"- {_moment(s.event_date)}"
            f"｜{SCHEDULE_TYPE_LABELS.get(s.schedule_type, s.schedule_type)}"
            f"｜{s.title}"
            + (f"｜案件 {s.case_no}" if s.case_no else "")
            for s in upcoming[:PERSONAL_CONTEXT_MAX_SCHEDULES]
        )
        items.append(
            {
                "kind": "schedule",
                "label": f"未来 7 天 {len(upcoming)} 项日程",
                "detail": "含开庭与期限",
                "link": _link(current.role, "/schedule"),
            }
        )
    if not schedule_lines:
        schedule_lines.append("今日与未来 7 天无待办日程")
    blocks.append(("三、日程", schedule_lines))

    today = date.today()
    active_contracts = [c for c in contracts if c.status == "active"]
    expiring = [
        c for c in active_contracts if c.end_date and 0 <= (c.end_date - today).days <= 30
    ]
    contract_lines = [
        (
            f"共 {len(contracts)} 份，生效中 {len(active_contracts)} 份"
            + (f"，30 天内到期 {len(expiring)} 份" if expiring else "")
        )
    ]
    for c in expiring[:PERSONAL_CONTEXT_MAX_CONTRACTS]:
        line = (
            f"- {c.name}｜{CONTRACT_STATUS_LABELS.get(c.status, c.status)}"
            f"｜金额 {_money(c.amount)}"
        )
        if c.end_date:
            line += f"｜到期 {_day(c.end_date)}（{(c.end_date - today).days} 天后）"
        else:
            line += "｜到期日未登记"
        contract_lines.append(line)
        items.append(
            {
                "kind": "contract",
                "label": c.name,
                "detail": "30 天内到期",
                "link": _link(current.role, f"/contracts/{c.id}"),
            }
        )
    blocks.append(("四、合同", contract_lines))

    counts = {
        "cases": total,
        "collects": len(collects),
        "schedules": len(today_schedules) + len(upcoming),
        "contracts": len(contracts),
    }

    return blocks, items, counts


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------


async def build_business_snapshot(
    db: AsyncSession, current: User
) -> PersonalContext:
    """按角色取业务快照；任何取数异常都退化为空上下文。

    没有 ``question`` 参数是有意为之：这个入口只回答业务问题，不需要按问题
    判断"该不该带明细"。以前那版要靠关键词猜意图，猜错的代价是问费用却得到
    一段收费规则——拆成独立模块后，判断本身就不存在了。
    """
    as_of = datetime.now().strftime("%Y-%m-%d %H:%M")

    try:
        if current.role == "client":
            blocks, items, counts = await _client_blocks(db, current)
        elif current.role in ("lawyer", "admin"):
            blocks, items, counts = await _staff_blocks(db, current)
        else:
            return PersonalContext(scope=current.role, as_of=as_of)
    except Exception:  # 业务数据取不到不该让整个请求失败
        logger.exception("本人业务快照构建失败 | user=%s", current.username)
        return PersonalContext(scope=current.role, as_of=as_of)

    text, truncated = business_prompts.render_business_context(
        as_of=as_of,
        blocks=blocks,
        max_chars=PERSONAL_CONTEXT_MAX_CHARS,
    )
    if truncated:
        logger.info("业务快照超预算已裁剪 | user=%s | %d 字", current.username, len(text))
    return PersonalContext(
        scope=current.role,
        as_of=as_of,
        text=text,
        items=items,
        counts=counts,
        truncated=truncated,
    )
