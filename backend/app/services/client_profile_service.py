"""客户画像的数据聚合与脱敏（任务拆解 9.7.2 / 9.7.4）。

画像的质量取决于「律师手上到底有哪些关于这位客户的事实」。这个模块把分散在六个
地方的数据收拢成 :class:`ClientBundle`，供 :mod:`app.services.ai_service` 拼提示词：

1. 客户档案（类型、来源、分级、漏斗状态、负责律师、建档时间、备注）
2. 跟进记录（方式、时间、内容、下次跟进；逾期单独标注）
3. 关联案件（案号、案由、阶段、标的额、法院）
4. 合同（名称、类型、金额、状态、AI 审查结论）
5. 收费与回款（方案金额、应收/已收/未收、逾期期次）
6. 沟通留言（最近往来、未读、客户主动咨询的主题）

**为什么按这个顺序排。** 判断客户「想不想成交、会不会流失、能不能回款」最直接的
证据是跟进说了什么、有没有案子在办、钱收到哪一步；合同条款与闲聊消息的信息密度
最低。超出预算时从尾部先砍，并把砍掉什么写进 ``skipped``，让画像的「数据缺口」
能如实说明。

**脱敏只作用于送入模型的文本（9.7.4）。** 身份证、手机号、邮箱、银行卡、详细
地址与个人姓名在拼装提示词前打码；数据库里的原文一字不改——律师在页面上看到的
仍是完整档案。机构名称不打码：它不是自然人敏感信息，且行业与规模是画像的关键
输入。打码后模型看到「张*」，提示词另行要求它用「该客户」指代、不得还原。

**权限收在入口。** 复用 :func:`app.services.client_service.get_client` 的行级
隔离：律师只能给自己负责的客户生成画像，管理员不限；客户账号直接 403，因为画像
里会有「价格敏感」「可能流失」这类不适合给客户本人看的内部判断。
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.masking import mask_sensitive
from app.config import settings
from app.core.exceptions import Forbidden
from app.core.utils import mask_id_no
from app.models.billing import FeePeriod, FeePlan
from app.models.case import Case
from app.models.contract import Contract
from app.models.follow import FollowRecord
from app.models.message import Message
from app.models.user import User
from app.services import client_service

logger = logging.getLogger(__name__)

__all__ = [
    "CASE_STATUS_LABELS",
    "CLIENT_STATUS_LABELS",
    "ClientBundle",
    "collect_client_bundle",
]

CLIENT_TYPE_LABELS = {"personal": "个人", "company": "机构"}
CLIENT_STATUS_LABELS = {
    "potential": "潜在（尚未成交）",
    "deal": "已成交",
    "lost": "已流失",
}
LEVEL_LABELS = {"vip": "VIP", "normal": "普通"}
CASE_STATUS_LABELS = {
    "consulting": "咨询中",
    "filed": "已立案",
    "handling": "办理中",
    "pending_close": "待结案",
    "closed": "已结案",
    "withdrawn": "已退案",
}
CASE_TYPE_LABELS = {"litigation": "诉讼", "non_litigation": "非诉"}
CONTRACT_STATUS_LABELS = {
    "draft": "草稿",
    "active": "生效中",
    "expired": "已到期",
    "terminated": "已终止",
}
FEE_TYPE_LABELS = {
    "fixed": "固定收费",
    "ratio": "比例收费",
    "risk": "风险代理",
    "hourly": "计时收费",
}
METHOD_LABELS = {"phone": "电话", "wechat": "微信", "visit": "面访", "email": "邮件"}

# 只有这些状态的案件算「在办」，用于统计客户当前的委托深度
_ACTIVE_STATUSES = ("consulting", "filed", "handling", "pending_close")


@dataclass(slots=True)
class ClientBundle:
    """一位客户的画像输入。字段均为值类型，可安全跨请求边界传递。"""

    client_id: int
    name: str
    masked_name: str
    meta: dict[str, str]
    follows: list[str] = field(default_factory=list)
    cases: list[str] = field(default_factory=list)
    contracts: list[str] = field(default_factory=list)
    billing: list[str] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    stats: dict[str, Any] = field(default_factory=dict)
    total_chars: int = 0
    truncated: bool = False
    masked_hits: dict[str, int] = field(default_factory=dict)

    @property
    def masked_summary(self) -> str:
        labels = {
            "id_card": "身份证",
            "bank_card": "银行卡",
            "phone": "手机号",
            "email": "邮箱",
            "name": "姓名",
            "address": "地址",
        }
        return "、".join(
            f"{labels.get(key, key)}×{count}"
            for key, count in self.masked_hits.items()
            if count
        )


class _Masker:
    """累积式脱敏：每次调用返回打码文本，同时累计命中次数供前端提示。"""

    def __init__(self) -> None:
        self.hits: Counter[str] = Counter()

    def __call__(self, text: str | None) -> str:
        if not text:
            return ""
        result = mask_sensitive(text)
        self.hits.update(result.hits)
        return result.text

    def phone(self, value: str | None) -> str:
        """手机号交给通用规则；座机等其余号码保留前 4 后 2，避免整段暴露。"""
        if not value:
            return ""
        if len(value) >= 11:
            return self(value)
        if len(value) <= 6:
            masked = value[:1] + "*" * max(len(value) - 1, 0)
        else:
            masked = f"{value[:4]}**{value[-2:]}"
        self.hits["phone"] += 1
        return masked

    def address(self, value: str | None) -> str:
        """地址只保留到区县一级：详细门牌对画像没有价值，泄露风险却是实打实的。"""
        if not value:
            return ""
        text = value.strip()
        # 6 字以内基本是「省+市」，不含门牌，保留；更长的截到区县一级
        masked = text if len(text) <= 6 else f"{text[:9]}…（详址已省略）"
        self.hits["address"] += 1
        return masked

    def person_name(self, name: str, *, is_company: bool) -> str:
        """个人姓名打码，机构名称保留（行业与规模是画像的关键信息）。"""
        if is_company or not name:
            return name
        if len(name) <= 1:
            return name
        self.hits["name"] += 1
        return name[0] + "*" * (len(name) - 1)


def _fmt_time(value: datetime | date | None, *, with_time: bool = False) -> str:
    if value is None:
        return "未登记"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M" if with_time else "%Y-%m-%d")
    return value.strftime("%Y-%m-%d")


def _fmt_amount(value: Any) -> str:
    if value is None:
        return "未填写"
    try:
        amount = Decimal(str(value))
    except (ArithmeticError, ValueError):
        return "未填写"
    return f"¥{amount:,.2f}" if amount else "未填写"


def _days_since(value: datetime | date | None, now: datetime) -> int | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        delta = now - value
    else:
        delta = now.date() - value
    return delta.days


async def _owner_name(db: AsyncSession, lawyer_id: int | None) -> str:
    if lawyer_id is None:
        return "未分配"
    lawyer = await db.get(User, lawyer_id)
    if lawyer is None:
        return "未分配"
    return lawyer.real_name or lawyer.username


async def _load_follows(
    db: AsyncSession, client_id: int, masker: _Masker
) -> tuple[list[str], int, datetime | None, date | None]:
    """最近若干条跟进，返回 ``(格式化行, 总条数, 最近跟进时间, 下次跟进日期)``。"""
    total = await db.scalar(
        select(func.count())
        .select_from(FollowRecord)
        .where(FollowRecord.client_id == client_id)
    )
    rows = (
        (
            await db.execute(
                select(FollowRecord)
                .where(FollowRecord.client_id == client_id)
                .order_by(FollowRecord.created_at.desc(), FollowRecord.id.desc())
                .limit(settings.client_profile_max_follows)
            )
        )
        .scalars()
        .all()
    )

    # 跟进人姓名单独取，避免 N+1
    user_ids = {row.user_id for row in rows}
    names: dict[int, str] = {}
    if user_ids:
        users = (
            (
                await db.execute(
                    select(User.id, User.real_name, User.username).where(
                        User.id.in_(user_ids)
                    )
                )
            )
            .all()
        )
        names = {uid: (real or uname) for uid, real, uname in users}

    lines: list[str] = []
    for row in rows:
        method = METHOD_LABELS.get(row.method, row.method)
        content = masker(row.content or "").strip() or "（无文字内容）"
        content = content[: settings.client_profile_follow_chars]
        line = (
            f"{_fmt_time(row.created_at, with_time=True)}｜{method}"
            f"｜{names.get(row.user_id, '律师')}｜{content}"
        )
        if row.next_follow_date:
            line += f"（约定下次跟进 {_fmt_time(row.next_follow_date)}）"
        lines.append(line)

    latest_at = rows[0].created_at if rows else None
    next_date = next(
        (row.next_follow_date for row in rows if row.next_follow_date), None
    )
    return lines, int(total or 0), latest_at, next_date


async def _load_cases(
    db: AsyncSession, client_id: int, masker: _Masker
) -> tuple[list[str], dict[str, int], list[str]]:
    """返回 ``(格式化行, 统计, 对方当事人名单)``。

    名单用于后续别名字典：案件标题里常直接写当事人姓名（「邓丽与张伟离婚…」），
    单靠脱敏正则识别不出来，需要拿已知姓名做整词替换。
    """
    total = await db.scalar(
        select(func.count()).select_from(Case).where(Case.client_id == client_id)
    )
    active = await db.scalar(
        select(func.count())
        .select_from(Case)
        .where(Case.client_id == client_id, Case.status.in_(_ACTIVE_STATUSES))
    )
    rows = (
        (
            await db.execute(
                select(Case)
                .where(Case.client_id == client_id)
                .order_by(Case.created_at.desc(), Case.id.desc())
                .limit(settings.client_profile_max_cases)
            )
        )
        .scalars()
        .all()
    )

    lines: list[str] = []
    parties: list[str] = []
    for case in rows:
        if case.opposing_party:
            parties.append(case.opposing_party)
        parts = [
            case.case_no,
            case.title,
            case.case_cause or "案由未填写",
            CASE_TYPE_LABELS.get(case.case_type, case.case_type),
            CASE_STATUS_LABELS.get(case.status, case.status),
            f"标的 {_fmt_amount(case.amount)}",
        ]
        if case.court:
            parts.append(case.court)
        if case.opposing_party:
            parts.append(f"对方 {masker(case.opposing_party)}")
        parts.append(f"立案 {_fmt_time(case.created_at)}")
        if case.closed_at:
            parts.append(f"结案 {_fmt_time(case.closed_at)}")
        lines.append("｜".join(parts))

    return lines, {"total": int(total or 0), "active": int(active or 0)}, parties


async def _load_contracts(
    db: AsyncSession, client_id: int
) -> tuple[list[str], dict[str, int]]:
    total = await db.scalar(
        select(func.count())
        .select_from(Contract)
        .where(Contract.client_id == client_id)
    )
    rows = (
        (
            await db.execute(
                select(Contract)
                .where(Contract.client_id == client_id)
                .order_by(Contract.created_at.desc(), Contract.id.desc())
                .limit(settings.client_profile_max_contracts)
            )
        )
        .scalars()
        .all()
    )

    lines: list[str] = []
    reviewed = 0
    risk_total = 0
    for contract in rows:
        parts = [
            contract.name,
            contract.contract_type or "类型未填写",
            _fmt_amount(contract.amount),
            CONTRACT_STATUS_LABELS.get(contract.status, contract.status),
        ]
        if contract.start_date:
            parts.append(f"生效 {_fmt_time(contract.start_date)}")
        if contract.end_date:
            parts.append(f"到期 {_fmt_time(contract.end_date)}")
        report = contract.ai_review_report
        if isinstance(report, dict):
            risks = report.get("risks")
            if isinstance(risks, list):
                reviewed += 1
                risk_total += len(risks)
                parts.append(f"AI 审查发现 {len(risks)} 处风险")
        lines.append("｜".join(parts))

    return lines, {"total": int(total or 0), "reviewed": reviewed, "risks": risk_total}


async def _load_billing(
    db: AsyncSession, client_id: int
) -> tuple[list[str], dict[str, Any]]:
    """按「方案 → 期次」汇总应收/已收/未收与逾期期次。"""
    rows = (
        await db.execute(
            select(FeePlan, Case.case_no, Case.title)
            .join(Case, Case.id == FeePlan.case_id)
            .where(Case.client_id == client_id)
            .order_by(FeePlan.created_at.desc(), FeePlan.id.desc())
            .limit(settings.client_profile_max_fee_plans)
        )
    ).all()

    plan_ids = [plan.id for plan, _case_no, _title in rows]
    periods: list[FeePeriod] = []
    if plan_ids:
        periods = list(
            (
                await db.execute(
                    select(FeePeriod).where(FeePeriod.fee_plan_id.in_(plan_ids))
                )
            )
            .scalars()
            .all()
        )

    today = date.today()
    by_plan: dict[int, list[FeePeriod]] = {}
    for period in periods:
        by_plan.setdefault(period.fee_plan_id, []).append(period)

    lines: list[str] = []
    due_total = Decimal("0.00")
    paid_total = Decimal("0.00")
    overdue = 0
    for plan, case_no, title in rows:
        items = by_plan.get(plan.id, [])
        due = sum((Decimal(str(item.due_amount or 0)) for item in items), Decimal(0))
        paid = sum((Decimal(str(item.paid_amount or 0)) for item in items), Decimal(0))
        due_total += due
        paid_total += paid
        plan_overdue = [
            item
            for item in items
            if item.status != "paid" and item.due_date and item.due_date < today
        ]
        overdue += len(plan_overdue)
        line = (
            f"{case_no}《{title}》｜{FEE_TYPE_LABELS.get(plan.fee_type, plan.fee_type)}"
            f"｜应收 {_fmt_amount(due)}｜已收 {_fmt_amount(paid)}"
            f"｜未收 {_fmt_amount(due - paid)}"
        )
        if plan_overdue:
            earliest = min(item.due_date for item in plan_overdue if item.due_date)
            line += (
                f"｜{len(plan_overdue)} 期逾期（最早 {_fmt_time(earliest)}）"
            )
        if plan.description:
            line += f"｜{plan.description[:120]}"
        lines.append(line)

    stats = {
        "plans": len(rows),
        "due_total": str(due_total),
        "paid_total": str(paid_total),
        "unpaid_total": str(due_total - paid_total),
        "overdue_periods": overdue,
    }
    return lines, stats


async def _load_messages(
    db: AsyncSession, client_id: int, masker: _Masker
) -> tuple[list[str], dict[str, int]]:
    total = await db.scalar(
        select(func.count()).select_from(Message).where(Message.client_id == client_id)
    )
    unread = await db.scalar(
        select(func.count())
        .select_from(Message)
        .where(
            Message.client_id == client_id,
            Message.sender_role == "client",
            Message.is_read.is_(False),
        )
    )
    rows = (
        (
            await db.execute(
                select(Message)
                .where(Message.client_id == client_id)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(settings.client_profile_max_messages)
            )
        )
        .scalars()
        .all()
    )

    lines: list[str] = []
    for row in reversed(rows):  # 按时间顺序展示，便于模型看出话题演变
        who = "客户" if row.sender_role == "client" else "律师"
        text = masker(row.content or "").strip() or "（仅附件）"
        text = text[: settings.client_profile_message_chars]
        lines.append(f"{_fmt_time(row.created_at)}｜{who}：{text}")

    return lines, {"total": int(total or 0), "unread": int(unread or 0)}


def _fit_budget(bundle: ClientBundle) -> None:
    """总字数超预算时，从信息密度最低的一类开始逐条丢弃，并记录被丢弃的数量。"""
    sections = ("follows", "cases", "billing", "messages", "contracts")
    limit = max(2000, settings.client_profile_max_chars)

    def total() -> int:
        return sum(
            len(item) for name in sections for item in getattr(bundle, name)
        )

    while total() > limit:
        dropped = False
        for name in reversed(sections):  # contracts → messages → billing → ...
            items: list[str] = getattr(bundle, name)
            if items:
                items.pop()
                bundle.skipped.append(f"部分{_SECTION_LABELS[name]}因超出本次篇幅未纳入")
                bundle.truncated = True
                dropped = True
                break
        if not dropped:
            break

    bundle.total_chars = total()


_SECTION_LABELS = {
    "follows": "跟进记录",
    "cases": "关联案件",
    "billing": "收费记录",
    "messages": "沟通记录",
    "contracts": "合同记录",
}

# 含这些词的「当事人」按机构处理，不做姓名打码
_ORG_HINTS = (
    "公司",
    "集团",
    "银行",
    "工厂",
    "厂",
    "店",
    "中心",
    "医院",
    "学校",
    "学院",
    "委员会",
    "政府",
    "工作室",
    "事务所",
    "合作社",
    "协会",
    "研究院",
    "商行",
    "门市",
)


def _looks_person(name: str | None) -> bool:
    """粗判一个当事人名是不是自然人：2~4 个汉字且不含机构后缀。"""
    text = (name or "").strip()
    if not 2 <= len(text) <= 4:
        return False
    if any(hint in text for hint in _ORG_HINTS):
        return False
    return all("\u4e00" <= ch <= "\u9fff" for ch in text)


def _mask_person(name: str) -> str:
    return name[0] + "*" * (len(name) - 1) if len(name) > 1 else name


def _apply_aliases(lines: list[str], alias: dict[str, str]) -> list[str]:
    """用已知姓名替换文本中的真名。

    正则脱敏只能识别「称谓 + 姓名」，而案件标题、合同名称里的姓名是裸串
    （「邓丽与张伟离婚后财产分割纠纷案」「武庸土地委派合同」）。这里拿客户姓名
    与对方当事人做整词替换，补上这个缺口。按长度倒序替换，避免短名先命中把
    长名切碎。
    """
    if not alias:
        return lines
    pairs = sorted(
        ((real, masked) for real, masked in alias.items() if real and real != masked),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    if not pairs:
        return lines
    result: list[str] = []
    for line in lines:
        for real, masked in pairs:
            line = line.replace(real, masked)
        result.append(line)
    return result


async def collect_client_bundle(
    db: AsyncSession, user: User, client_id: int
) -> ClientBundle:
    """聚合客户画像所需的全部输入（权限错误直接抛 403/404）。

    律师必须是该客户的负责律师；管理员不限；客户账号一律 403——画像包含
    「价格敏感」「回款风险」这类内部判断，不能给客户本人看到。
    """
    if user.role not in ("lawyer", "admin"):
        raise Forbidden("无权生成客户画像")

    client = await client_service.get_client(db, client_id, user)
    masker = _Masker()
    now = datetime.now()

    owner = await _owner_name(db, client.lawyer_id)
    follows, follow_total, latest_follow, next_follow = await _load_follows(
        db, client.id, masker
    )
    cases, case_stats, parties = await _load_cases(db, client.id, masker)
    contracts, contract_stats = await _load_contracts(db, client.id)
    billing, billing_stats = await _load_billing(db, client.id)
    messages, message_stats = await _load_messages(db, client.id, masker)

    is_company = client.client_type == "company"
    masked_name = masker.person_name(client.name, is_company=is_company)

    meta = {
        "客户名称": masked_name,
        "客户类型": CLIENT_TYPE_LABELS.get(client.client_type, client.client_type),
        "来源渠道": client.source_channel or "未登记",
        "漏斗状态": CLIENT_STATUS_LABELS.get(client.status, client.status),
        "客户分级": LEVEL_LABELS.get(client.level, client.level),
        "负责律师": owner,
        "建档时间": _fmt_time(client.created_at, with_time=True),
        "最近跟进": _fmt_time(latest_follow, with_time=True),
    }
    if next_follow:
        overdue = next_follow < now.date()
        meta["下次跟进"] = _fmt_time(next_follow) + ("（已逾期）" if overdue else "")
    if client.phone:
        meta["联系电话"] = masker.phone(client.phone)
    if client.id_no:
        meta["证件号"] = mask_id_no(client.id_no) or "已登记"
        masker.hits["id_card"] += 1
    if client.gender:
        meta["性别"] = client.gender
    if client.address:
        meta["联系地址"] = masker.address(client.address)
    if client.remark:
        meta["备注"] = masker(client.remark).strip()[:400]

    days = _days_since(latest_follow, now)
    stats: dict[str, Any] = {
        "follows": follow_total,
        "follows_shown": len(follows),
        "days_since_follow": days,
        "cases": case_stats["total"],
        "active_cases": case_stats["active"],
        "cases_shown": len(cases),
        "contracts": contract_stats["total"],
        "contracts_reviewed": contract_stats["reviewed"],
        "contract_risks": contract_stats["risks"],
        "messages": message_stats["total"],
        "unread": message_stats["unread"],
        "fee_plans": billing_stats["plans"],
        "due_total": billing_stats["due_total"],
        "paid_total": billing_stats["paid_total"],
        "unpaid_total": billing_stats["unpaid_total"],
        "overdue_periods": billing_stats["overdue_periods"],
    }

    skipped: list[str] = []
    if follow_total > len(follows):
        skipped.append(
            f"共有 {follow_total} 条跟进，仅纳入最近 {len(follows)} 条"
        )
    if case_stats["total"] > len(cases):
        skipped.append(f"共有 {case_stats['total']} 个案件，仅纳入最近 {len(cases)} 个")
    if contract_stats["total"] > len(contracts):
        skipped.append(
            f"共有 {contract_stats['total']} 份合同，仅纳入最近 {len(contracts)} 份"
        )
    if message_stats["total"] > len(messages):
        skipped.append(
            f"共有 {message_stats['total']} 条留言，仅纳入最近 {len(messages)} 条"
        )
    if follow_total == 0:
        skipped.append("没有跟进记录：无法判断沟通偏好与推进节奏")
    if case_stats["total"] == 0 and client.status == "deal":
        skipped.append("已成交但无关联案件：成交依据不明，建议补录案件或说明服务内容")

    bundle = ClientBundle(
        client_id=client.id,
        name=client.name,
        masked_name=masked_name,
        meta=meta,
        follows=follows,
        cases=cases,
        contracts=contracts,
        billing=billing,
        messages=messages,
        skipped=skipped,
        counts={
            "follows": follow_total,
            "cases": case_stats["total"],
            "contracts": contract_stats["total"],
            "messages": message_stats["total"],
            "fee_plans": billing_stats["plans"],
            "included": len(follows) + len(cases) + len(contracts) + len(messages),
        },
        stats=stats,
    )
    # 已知姓名整词替换：案件标题/合同名称里常直接写当事人姓名，正则识别不到
    alias: dict[str, str] = {}
    if client.client_type != "company":
        alias[client.name] = masked_name
    for party in parties:
        if _looks_person(party):
            alias[party] = _mask_person(party)
    for section in ("follows", "cases", "contracts", "billing", "messages"):
        setattr(bundle, section, _apply_aliases(getattr(bundle, section), alias))

    _fit_budget(bundle)
    bundle.masked_hits = dict(masker.hits)

    logger.info(
        "客户画像数据聚合 | client=%s | 跟进 %d / 案件 %d / 合同 %d / 留言 %d | "
        "%d 字 | 脱敏 %s",
        client.id,
        follow_total,
        case_stats["total"],
        contract_stats["total"],
        message_stats["total"],
        bundle.total_chars,
        bundle.masked_summary or "无",
    )
    return bundle
