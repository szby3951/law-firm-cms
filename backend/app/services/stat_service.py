"""统计报表服务（模块 10.1）。

两块口径：
- :func:`dashboard` 管理员全所大屏：KPI、收案/结案趋势、状态/案由/来源分布、
  律师办案量与创收排名、营收回款、合同到期、日程待办。
- :func:`my_stats` 律师个人工作台：本人承办案件、负责客户、创收、日程与待跟进。

约定：
- 律师范围一律以 ``case_lawyer.lawyer_id`` 为准（主办+协办），与收费、日程模块一致；
- 创收按「主办律师」归属（``duty='lead'``），避免一案多律师重复计入协办方；
- 金额统一走 ``Decimal``，占比保留两位小数；
- 时间窗口与 ``schedule_service`` 对齐：今日 = 当天 00:00~23:59:59，
  未来 N 天到第 N 天 23:59:59（不是 now + N×24h，否则第 N 天下午的日程会被漏掉）。
"""

from datetime import date, datetime, time, timedelta
from decimal import Decimal

from sqlalchemy import Select, and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden
from app.models.billing import FeePeriod, FeePlan, Payment
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.contract import Contract
from app.models.follow import FollowRecord
from app.models.schedule import Schedule
from app.models.user import User
from app.schemas.billing import BillingStatsOut
from app.schemas.schedule import SCHEDULE_TYPE_LABELS
from app.schemas.stats import (
    DashboardOut,
    DistributionItemOut,
    ExpiringSummaryOut,
    FollowUpOut,
    KpiOut,
    LawyerRankOut,
    MyKpiOut,
    MyStatsOut,
    StatusItemOut,
    TodoSummaryOut,
    TrendPointOut,
    UpcomingScheduleOut,
)
from app.services import billing_service
from app.services.case_service import STATUS_LABELS

ZERO = Decimal("0.00")

# 未结案状态（与首页「在办案件」口径一致）
ACTIVE_CASE_STATUSES = ("consulting", "filed", "handling", "pending_close")
# 状态分布展示顺序
STATUS_ORDER = ("consulting", "filed", "handling", "pending_close", "closed", "withdrawn")

TOP_CAUSE = 10
TOP_LAWYER = 10
UPCOMING_LIMIT = 5
FOLLOW_LIMIT = 5


# ---------------------------------------------------------------------------
# 通用工具
# ---------------------------------------------------------------------------


def _dec(value) -> Decimal:
    """把 SQL 聚合结果（None / float / str）统一成 Decimal。"""
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _day_start(value: date) -> datetime:
    """当天 00:00:00。"""
    return datetime.combine(value, time.min)


def _day_end(value: date) -> datetime:
    """当天 23:59:59.999999。"""
    return datetime.combine(value, time.max)


def _shift_month(value: date, months: int) -> date:
    """在某月 1 日的基础上前后平移 N 个月。"""
    total = value.year * 12 + (value.month - 1) + months
    return date(total // 12, total % 12 + 1, 1)


def _month_series(months: int, end: date | None = None) -> list[date]:
    """最近 N 个月的月份序列（升序，每月 1 日）。"""
    last = (end or date.today()).replace(day=1)
    first = _shift_month(last, -(months - 1))
    out: list[date] = []
    cursor = first
    while cursor <= last:
        out.append(cursor)
        cursor = _shift_month(cursor, 1)
    return out


def _ratio(part: int, total: int) -> float:
    """占比（百分比，保留两位小数）。"""
    if not total:
        return 0.0
    return round(part / total * 100, 2)


def _lawyer_case_scope(current: User):
    """律师可见案件的过滤条件；管理员返回 None（不限制）。"""
    if current.role == "admin":
        return None
    return Case.id.in_(
        select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
    )


async def _status_counts(db: AsyncSession, scope) -> dict[str, int]:
    """按状态统计案件数。"""
    stmt: Select = select(Case.status, func.count()).group_by(Case.status)
    if scope is not None:
        stmt = stmt.where(scope)
    rows = (await db.execute(stmt)).all()
    return {str(status): int(count) for status, count in rows}


def _status_dist(counts: dict[str, int]) -> list[StatusItemOut]:
    """把状态计数展开成固定顺序的分布列表（缺项补 0）。"""
    return [
        StatusItemOut(
            status=status,
            label=STATUS_LABELS.get(status, status),
            count=counts.get(status, 0),
        )
        for status in STATUS_ORDER
    ]


async def _trend(db: AsyncSession, months: int, scope) -> list[TrendPointOut]:
    """收案/结案月度趋势，缺失月份补 0。"""
    series = _month_series(months)
    start = _day_start(series[0])
    opened_key = func.date_format(Case.created_at, "%Y-%m")
    closed_key = func.date_format(Case.closed_at, "%Y-%m")

    opened_stmt = (
        select(opened_key, func.count())
        .where(Case.created_at >= start)
        .group_by(opened_key)
    )
    closed_stmt = (
        select(closed_key, func.count())
        .where(Case.closed_at.is_not(None), Case.closed_at >= start)
        .group_by(closed_key)
    )
    if scope is not None:
        opened_stmt = opened_stmt.where(scope)
        closed_stmt = closed_stmt.where(scope)

    opened = {str(k): int(v) for k, v in (await db.execute(opened_stmt)).all()}
    closed = {str(k): int(v) for k, v in (await db.execute(closed_stmt)).all()}

    cross_year = series[0].year != series[-1].year
    points: list[TrendPointOut] = []
    for month in series:
        key = f"{month.year:04d}-{month.month:02d}"
        label = f"{str(month.year)[2:]}/{month.month}" if cross_year else f"{month.month}月"
        points.append(
            TrendPointOut(
                month=key,
                label=label,
                opened=opened.get(key, 0),
                closed=closed.get(key, 0),
            )
        )
    return points


async def _cause_dist(db: AsyncSession, scope) -> list[DistributionItemOut]:
    """案由分布（前 10，空案由归入「未填写」）。"""
    cause = func.coalesce(func.nullif(Case.case_cause, ""), "未填写")
    stmt = select(cause, func.count().label("c")).group_by(cause)
    if scope is not None:
        stmt = stmt.where(scope)
    rows = (await db.execute(stmt.order_by(func.count().desc()))).all()
    total = sum(int(count) for _, count in rows)
    return [
        DistributionItemOut(name=str(name), count=int(count), ratio=_ratio(int(count), total))
        for name, count in rows[:TOP_CAUSE]
    ]


async def _source_dist(db: AsyncSession) -> list[DistributionItemOut]:
    """客户来源渠道占比（空值归入「未填写」）。"""
    source = func.coalesce(func.nullif(ClientProfile.source_channel, ""), "未填写")
    stmt = select(source, func.count().label("c")).group_by(source)
    rows = (await db.execute(stmt.order_by(func.count().desc()))).all()
    total = sum(int(count) for _, count in rows)
    return [
        DistributionItemOut(name=str(name), count=int(count), ratio=_ratio(int(count), total))
        for name, count in rows
    ]


async def _lawyer_ranking(db: AsyncSession) -> list[LawyerRankOut]:
    """律师办案量与创收排名（前 10，按创收降序）。

    办案量取 ``case_lawyer`` 全量；创收只认 ``duty='lead'`` 的实收合计。
    """
    active_flag = case((Case.status.in_(ACTIVE_CASE_STATUSES), 1), else_=0)
    lead_flag = case((CaseLawyer.duty == "lead", 1), else_=0)
    closed_flag = case((Case.status == "closed", 1), else_=0)

    work_stmt = (
        select(
            CaseLawyer.lawyer_id,
            func.count(Case.id).label("case_count"),
            func.sum(lead_flag).label("lead_count"),
            func.sum(active_flag).label("active_count"),
            func.sum(closed_flag).label("closed_count"),
        )
        .join(Case, Case.id == CaseLawyer.case_id)
        .group_by(CaseLawyer.lawyer_id)
    )
    work_rows = (await db.execute(work_stmt)).all()
    if not work_rows:
        return []

    income_stmt = (
        select(CaseLawyer.lawyer_id, func.coalesce(func.sum(Payment.amount), 0))
        .join(Case, Case.id == CaseLawyer.case_id)
        .join(FeePlan, FeePlan.case_id == Case.id)
        .join(FeePeriod, FeePeriod.fee_plan_id == FeePlan.id)
        .join(Payment, Payment.fee_period_id == FeePeriod.id)
        .where(CaseLawyer.duty == "lead")
        .group_by(CaseLawyer.lawyer_id)
    )
    income_map = {
        int(lawyer_id): _dec(amount)
        for lawyer_id, amount in (await db.execute(income_stmt)).all()
    }

    lawyer_ids = [int(row[0]) for row in work_rows]
    name_rows = (
        await db.execute(
            select(User.id, User.real_name).where(User.id.in_(lawyer_ids))
        )
    ).all()
    name_map = {int(uid): (name or f"律师#{uid}") for uid, name in name_rows}

    items = [
        LawyerRankOut(
            lawyer_id=int(row[0]),
            name=name_map.get(int(row[0]), f"律师#{int(row[0])}"),
            case_count=int(row[1] or 0),
            lead_count=int(row[2] or 0),
            assist_count=int(row[1] or 0) - int(row[2] or 0),
            active_count=int(row[3] or 0),
            closed_count=int(row[4] or 0),
            income=income_map.get(int(row[0]), ZERO),
        )
        for row in work_rows
    ]
    items.sort(key=lambda x: (x.income, x.case_count), reverse=True)
    return items[:TOP_LAWYER]


async def _expiring_summary(db: AsyncSession) -> ExpiringSummaryOut:
    """生效中合同的到期预警分档（7/30/60 天内）。"""
    today = date.today()
    stmt = (
        select(
            func.sum(case((Contract.end_date <= today + timedelta(days=7), 1), else_=0)),
            func.sum(case((Contract.end_date <= today + timedelta(days=30), 1), else_=0)),
            func.sum(case((Contract.end_date <= today + timedelta(days=60), 1), else_=0)),
        )
        .select_from(Contract)
        .where(
            Contract.status == "active",
            Contract.end_date.is_not(None),
            Contract.end_date >= today,
        )
    )
    within_7, within_30, within_60 = (await db.execute(stmt)).one()
    return ExpiringSummaryOut(
        within_7=int(within_7 or 0),
        within_30=int(within_30 or 0),
        within_60=int(within_60 or 0),
    )


def _schedule_scope(current: User) -> list:
    """日程可见范围：管理员全所，律师限本人归属或本人承办案件下的日程。"""
    if current.role == "admin":
        return []
    conds = [Schedule.user_id == current.id]
    conds.append(
        Schedule.case_id.in_(
            select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
        )
    )
    return [or_(*conds)]


async def _todo_summary(db: AsyncSession, current: User) -> TodoSummaryOut:
    """今日 / 未来 7 天 / 逾期未办 三个计数。"""
    now = datetime.now()
    today_start = _day_start(now.date())
    today_end = _day_end(now.date())
    week_end = _day_end(now.date() + timedelta(days=7))
    conds = _schedule_scope(current)

    today_flag = case(
        (
            and_(
                Schedule.status != "cancelled",
                Schedule.event_date >= today_start,
                Schedule.event_date <= today_end,
            ),
            1,
        ),
        else_=0,
    )
    week_flag = case(
        (
            and_(
                Schedule.status == "pending",
                Schedule.event_date >= now,
                Schedule.event_date <= week_end,
            ),
            1,
        ),
        else_=0,
    )
    overdue_flag = case(
        (and_(Schedule.status == "pending", Schedule.event_date < now), 1),
        else_=0,
    )

    stmt = (
        select(func.sum(today_flag), func.sum(week_flag), func.sum(overdue_flag))
        .select_from(Schedule)
        .where(*conds)
    )
    today, week, overdue = (await db.execute(stmt)).one()
    return TodoSummaryOut(
        today=int(today or 0),
        week=int(week or 0),
        overdue=int(overdue or 0),
    )


async def _upcoming_schedules(
    db: AsyncSession, current: User, limit: int = UPCOMING_LIMIT
) -> list[UpcomingScheduleOut]:
    """未来 7 天待办日程（含案号与客户名）。"""
    now = datetime.now()
    week_end = _day_end(now.date() + timedelta(days=7))
    conds = _schedule_scope(current)

    stmt = (
        select(Schedule, Case.case_no, ClientProfile.name)
        .outerjoin(Case, Case.id == Schedule.case_id)
        .outerjoin(ClientProfile, ClientProfile.id == Schedule.client_id)
        .where(
            *conds,
            Schedule.status == "pending",
            Schedule.event_date >= now,
            Schedule.event_date <= week_end,
        )
        .order_by(Schedule.event_date.asc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        UpcomingScheduleOut(
            id=item.id,
            title=item.title,
            schedule_type=item.schedule_type,
            type_label=SCHEDULE_TYPE_LABELS.get(item.schedule_type, item.schedule_type),
            event_date=item.event_date,
            case_no=case_no,
            client_name=client_name,
        )
        for item, case_no, client_name in rows
    ]


def _latest_follow_ids(current: User):
    """每个客户在本律师名下的最新一条跟进记录 id。

    只认最新一条：律师再次跟进后即使没填新的下次日期，旧记录的
    约定日期也不应继续把客户挂在待跟进里。
    """
    return (
        select(func.max(FollowRecord.id))
        .where(FollowRecord.user_id == current.id)
        .group_by(FollowRecord.client_id)
        .scalar_subquery()
    )


async def _follow_ups(db: AsyncSession, current: User) -> list[FollowUpOut]:
    """到期需跟进的客户（按约定日期升序，最多 5 位）。"""
    today = date.today()
    stmt = (
        select(ClientProfile.id, ClientProfile.name, FollowRecord.next_follow_date)
        .join(FollowRecord, FollowRecord.client_id == ClientProfile.id)
        .where(
            FollowRecord.id.in_(_latest_follow_ids(current)),
            FollowRecord.next_follow_date.is_not(None),
            FollowRecord.next_follow_date <= today,
        )
        .order_by(FollowRecord.next_follow_date.asc())
        .limit(FOLLOW_LIMIT)
    )
    rows = (await db.execute(stmt)).all()
    return [
        FollowUpOut(
            client_id=int(client_id),
            client_name=name,
            next_follow_date=next_date,
            overdue_days=max(0, (today - next_date).days),
        )
        for client_id, name, next_date in rows
    ]


async def _follow_due_count(db: AsyncSession, current: User) -> int:
    """到期需跟进的客户总数（每客户只算最新一条记录，天然去重）。"""
    stmt = (
        select(func.count())
        .select_from(FollowRecord)
        .where(
            FollowRecord.id.in_(_latest_follow_ids(current)),
            FollowRecord.next_follow_date.is_not(None),
            FollowRecord.next_follow_date <= date.today(),
        )
    )
    return int(await db.scalar(stmt) or 0)


async def _client_count(db: AsyncSession, current: User) -> int:
    """在册客户数：管理员全所，律师仅本人负责的客户。"""
    stmt = select(func.count()).select_from(ClientProfile)
    if current.role != "admin":
        stmt = stmt.where(ClientProfile.lawyer_id == current.id)
    return int(await db.scalar(stmt) or 0)


async def _new_clients_this_month(db: AsyncSession, current: User) -> int:
    """本月新增客户数。"""
    today = date.today()
    stmt = (
        select(func.count())
        .select_from(ClientProfile)
        .where(
            func.year(ClientProfile.created_at) == today.year,
            func.month(ClientProfile.created_at) == today.month,
        )
    )
    if current.role != "admin":
        stmt = stmt.where(ClientProfile.lawyer_id == current.id)
    return int(await db.scalar(stmt) or 0)


async def _year_income(db: AsyncSession, current: User) -> Decimal:
    """本年实收（律师按本人案件范围）。"""
    stmt = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(FeePeriod, FeePeriod.id == Payment.fee_period_id)
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .where(func.year(Payment.paid_at) == date.today().year)
    )
    if current.role != "admin":
        stmt = stmt.where(
            FeePlan.case_id.in_(
                select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
            )
        )
    return _dec(await db.scalar(stmt))


async def _billing(db: AsyncSession, current: User) -> BillingStatsOut:
    """复用收费模块的营收统计，保证与 /api/billing/stats 口径一致。"""
    return await billing_service.get_billing_stats(db, current)


# ---------------------------------------------------------------------------
# 管理员大屏
# ---------------------------------------------------------------------------


async def dashboard(
    db: AsyncSession, current: User, months: int = 12
) -> DashboardOut:
    """管理员统计大屏：全所数据。"""
    if current.role != "admin":
        raise Forbidden("统计大屏仅管理员可查看，律师请使用个人工作台")
    if not 1 <= months <= 36:
        raise BadRequest("月份跨度需在 1~36 之间")

    counts = await _status_counts(db, None)
    active_cases = sum(counts.get(s, 0) for s in ACTIVE_CASE_STATUSES)
    total_cases = sum(counts.values())

    billing = await _billing(db, current)
    expiring = await _expiring_summary(db)
    todo = await _todo_summary(db, current)

    return DashboardOut(
        generated_at=datetime.now(),
        months=months,
        kpi=KpiOut(
            active_cases=active_cases,
            total_cases=total_cases,
            closed_cases=counts.get("closed", 0),
            clients=await _client_count(db, current),
            new_clients=await _new_clients_this_month(db, current),
            month_income=billing.month_income,
            collection_rate=billing.collection_rate,
            expiring_contracts=expiring.within_30,
            today_todos=todo.today,
            week_todos=todo.week,
        ),
        case_trend=await _trend(db, months, None),
        case_status=_status_dist(counts),
        case_cause=await _cause_dist(db, None),
        lawyer_ranking=await _lawyer_ranking(db),
        client_source=await _source_dist(db),
        billing=billing,
        expiring=expiring,
        todo=todo,
    )


# ---------------------------------------------------------------------------
# 律师个人工作台
# ---------------------------------------------------------------------------


async def my_stats(
    db: AsyncSession, current: User, months: int = 6
) -> MyStatsOut:
    """律师个人工作台：本人承办案件、负责客户、创收与待办。"""
    if current.role != "lawyer":
        raise Forbidden("该接口仅供律师使用，管理员请查看统计大屏")
    if not 1 <= months <= 36:
        raise BadRequest("月份跨度需在 1~36 之间")

    scope = _lawyer_case_scope(current)
    counts = await _status_counts(db, scope)
    active_cases = sum(counts.get(s, 0) for s in ACTIVE_CASE_STATUSES)
    total_cases = sum(counts.values())

    billing = await _billing(db, current)
    todo = await _todo_summary(db, current)
    follows = await _follow_ups(db, current)

    return MyStatsOut(
        generated_at=datetime.now(),
        months=months,
        kpi=MyKpiOut(
            active_cases=active_cases,
            total_cases=total_cases,
            closed_cases=counts.get("closed", 0),
            clients=await _client_count(db, current),
            month_income=billing.month_income,
            year_income=await _year_income(db, current),
            today_todos=todo.today,
            week_todos=todo.week,
            follow_due=await _follow_due_count(db, current),
        ),
        case_trend=await _trend(db, months, scope),
        case_status=_status_dist(counts),
        upcoming_schedules=await _upcoming_schedules(db, current),
        follow_clients=follows,
        billing=billing,
    )
