"""收费管理业务逻辑。

核心链路：收费方案 → 拆分收费期次 → 收款登记（累计实收自动联动期次状态）
→ 催收清单 / 营收统计。权限沿用案件模块的行级隔离规则：

- 管理员：全所数据。
- 律师：仅本人主办或协办案件下的收费。
- 客户：只读，走 ``/api/my/bills`` 且仅限本人委托的账单。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.billing import FeePeriod, FeePlan, Payment
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.user import User
from app.schemas.billing import (
    AMOUNT_TOLERANCE,
    BillingStatsOut,
    BillOut,
    CollectItemOut,
    FeePeriodIn,
    FeePeriodOut,
    FeePlanIn,
    PaymentIn,
    PaymentInvoiceIn,
)

ZERO = Decimal("0.00")


# ---------------------------------------------------------------------------
# 权限与通用小工具
# ---------------------------------------------------------------------------


async def _case_lawyer_ids(db: AsyncSession, case_id: int) -> set[int]:
    """返回案件全部承办律师 id（主办 + 协办）。"""
    rows = (
        (
            await db.execute(
                select(CaseLawyer.lawyer_id).where(CaseLawyer.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    return set(rows)


async def _assert_case_access(db: AsyncSession, case_id: int, current: User) -> None:
    """收费写操作的案件权限：管理员不限，律师仅本人承办案件。"""
    if current.role == "admin":
        return
    if current.role != "lawyer":
        raise Forbidden("无权操作该案件的收费")
    if current.id not in await _case_lawyer_ids(db, case_id):
        raise Forbidden("只能操作本人承办案件的收费")


def _scope_stmt(stmt, current: User):
    """给查询附加角色数据范围（以 ``FeePlan.case_id`` 为准）。"""
    if current.role == "admin":
        return stmt
    if current.role == "client":
        raise Forbidden("客户无权查看收费台账")
    return stmt.where(
        FeePlan.case_id.in_(
            select(CaseLawyer.case_id).where(CaseLawyer.lawyer_id == current.id)
        )
    )


def _overdue_days(due_date: date | None) -> int:
    """逾期天数：未到期或未设置应收日期返回 0。"""
    if due_date is None:
        return 0
    delta = (date.today() - due_date).days
    return max(0, delta)


def _dec(value) -> Decimal:
    """把 SQL 聚合结果（可能为 None / float / str）统一成 Decimal。"""
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def to_period_out(period: FeePeriod) -> FeePeriodOut:
    """期次输出：补算未收金额与逾期天数（非数据库字段）。

    收款登记、在线支付两条链路都返回期次最新状态，统一在此构造避免各写一遍。
    """
    due = _dec(period.due_amount)
    paid = _dec(period.paid_amount)
    return FeePeriodOut(
        id=period.id,
        fee_plan_id=period.fee_plan_id,
        period_no=period.period_no,
        due_amount=due,
        paid_amount=paid,
        unpaid_amount=due - paid,
        due_date=period.due_date,
        status=period.status,
        overdue_days=_overdue_days(period.due_date),
        created_at=period.created_at,
    )


# 发票状态优先级：已开票 > 申请中 > 未开票
_INVOICE_PRIORITY = {"issued": 3, "applied": 2, "none": 1}


def _invoice_priority(status: str | None) -> int:
    """发票状态优先级，用于一期多次收款时挑出"最深"的开票进度。"""
    return _INVOICE_PRIORITY.get(status or "none", 1)


# ---------------------------------------------------------------------------
# 方案上下文注入（案件号、案件标题、客户、金额汇总）
# ---------------------------------------------------------------------------


async def _attach_plan_context(
    db: AsyncSession, plans: list[FeePlan]
) -> list[FeePlan]:
    """批量注入案件的编号/标题、客户信息与期次金额汇总。

    供 ``FeePlanOut`` 序列化输出，避免逐条查询造成 N+1。
    """
    if not plans:
        return plans

    plan_ids = [p.id for p in plans]
    case_ids = {p.case_id for p in plans}

    # 期次汇总：应收 / 已收 / 期次数
    agg_rows = (
        await db.execute(
            select(
                FeePeriod.fee_plan_id,
                func.coalesce(func.sum(FeePeriod.due_amount), 0),
                func.coalesce(func.sum(FeePeriod.paid_amount), 0),
                func.count(FeePeriod.id),
            )
            .where(FeePeriod.fee_plan_id.in_(plan_ids))
            .group_by(FeePeriod.fee_plan_id)
        )
    ).all()
    agg = {pid: (_dec(due), _dec(paid), int(cnt)) for pid, due, paid, cnt in agg_rows}

    # 案件 + 委托客户
    case_rows = (
        await db.execute(
            select(
                Case.id,
                Case.case_no,
                Case.title,
                Case.client_id,
                ClientProfile.name,
            )
            .join(ClientProfile, ClientProfile.id == Case.client_id, isouter=True)
            .where(Case.id.in_(case_ids))
        )
    ).all()
    case_map = {
        cid: (case_no, title, client_id, client_name)
        for cid, case_no, title, client_id, client_name in case_rows
    }

    for plan in plans:
        case_no, title, client_id, client_name = case_map.get(
            plan.case_id, (None, None, None, None)
        )
        plan.case_no = case_no
        plan.case_title = title
        plan.client_id = client_id
        plan.client_name = client_name
        due_total, paid_total, period_count = agg.get(plan.id, (ZERO, ZERO, 0))
        plan.due_total = due_total
        plan.paid_total = paid_total
        plan.period_count = period_count
    return plans


async def _get_plan_or_404(db: AsyncSession, plan_id: int) -> FeePlan:
    plan = await db.get(FeePlan, plan_id)
    if plan is None:
        raise NotFound("收费方案不存在")
    return plan


async def _get_period_or_404(db: AsyncSession, period_id: int) -> FeePeriod:
    period = await db.get(FeePeriod, period_id)
    if period is None:
        raise NotFound("收费期次不存在")
    return period


async def _assert_period_access(
    db: AsyncSession, period: FeePeriod, current: User
) -> FeePlan:
    """校验当前用户对某期次所属案件的收费权限，返回所属方案。"""
    plan = await db.get(FeePlan, period.fee_plan_id)
    if plan is None:
        raise NotFound("收费方案不存在")
    await _assert_case_access(db, plan.case_id, current)
    return plan


# ---------------------------------------------------------------------------
# 5.1.5 收费方案创建 / 期次生成
# ---------------------------------------------------------------------------


async def create_fee_plan(
    db: AsyncSession, payload: FeePlanIn, current: User
) -> FeePlan:
    """创建收费方案并按分期计划生成期次。

    ``periods`` 为空时自动生成单期（应收 = 收费总额）。
    """
    case = await db.get(Case, payload.case_id)
    if case is None:
        raise NotFound("案件不存在")
    await _assert_case_access(db, case.id, current)

    periods_in: list[FeePeriodIn] = list(payload.periods)
    if periods_in:
        # schema 已校验过一次，这里在服务层再兜一层，防止绕过
        diff = sum((p.due_amount for p in periods_in), Decimal(0)) - payload.total_amount
        if abs(diff) > AMOUNT_TOLERANCE:
            raise BadRequest("各期次应收合计与收费总额不一致")
    else:
        periods_in = [FeePeriodIn(due_amount=payload.total_amount)]

    plan = FeePlan(
        case_id=payload.case_id,
        fee_type=payload.fee_type,
        total_amount=payload.total_amount,
        description=payload.description,
    )
    db.add(plan)
    await db.flush()  # 取到 plan.id

    for idx, item in enumerate(periods_in, start=1):
        db.add(
            FeePeriod(
                fee_plan_id=plan.id,
                period_no=item.period_no or idx,
                due_amount=item.due_amount,
                paid_amount=ZERO,
                due_date=item.due_date,
                status="unpaid",
            )
        )

    await db.commit()
    await db.refresh(plan)
    await _attach_plan_context(db, [plan])
    return plan


async def add_fee_period(
    db: AsyncSession, plan_id: int, payload: FeePeriodIn, current: User
) -> FeePeriod:
    """向已有方案追加一个期次，并同步方案总额为新期次应收合计。"""
    plan = await _get_plan_or_404(db, plan_id)
    await _assert_case_access(db, plan.case_id, current)

    if payload.period_no is not None:
        exists = await db.scalar(
            select(FeePeriod.id).where(
                FeePeriod.fee_plan_id == plan_id,
                FeePeriod.period_no == payload.period_no,
            )
        )
        if exists:
            raise BadRequest(f"期次 {payload.period_no} 已存在，请使用其他序号")
        period_no = payload.period_no
    else:
        max_no = await db.scalar(
            select(func.coalesce(func.max(FeePeriod.period_no), 0)).where(
                FeePeriod.fee_plan_id == plan_id
            )
        )
        period_no = int(max_no or 0) + 1

    period = FeePeriod(
        fee_plan_id=plan_id,
        period_no=period_no,
        due_amount=payload.due_amount,
        paid_amount=ZERO,
        due_date=payload.due_date,
        status="unpaid",
    )
    db.add(period)
    await db.flush()

    # 方案总额跟随期次合计，保持「总额 = 各期应收之和」的一致性
    new_total = await db.scalar(
        select(func.coalesce(func.sum(FeePeriod.due_amount), 0)).where(
            FeePeriod.fee_plan_id == plan_id
        )
    )
    plan.total_amount = _dec(new_total)

    await db.commit()
    await db.refresh(period)
    return period


# ---------------------------------------------------------------------------
# 5.1.5 收款登记（自动联动期次状态）
# ---------------------------------------------------------------------------


async def register_payment(
    db: AsyncSession, period_id: int, payload: PaymentIn, current: User
) -> tuple[Payment, FeePeriod]:
    """登记一笔收款，自动更新期次已收金额与状态。

    规则：累计实收 < 应收 → ``partial``；累计实收 >= 应收 → ``paid``。
    超额收款直接拒绝，避免出现负数未收金额。
    """
    period = await _get_period_or_404(db, period_id)
    await _assert_period_access(db, period, current)

    # 行锁：防止并发收款导致累计值互相覆盖、超收
    period = (
        await db.execute(
            select(FeePeriod).where(FeePeriod.id == period_id).with_for_update()
        )
    ).scalar_one()

    unpaid = _dec(period.due_amount) - _dec(period.paid_amount)
    if payload.amount > unpaid:
        raise BadRequest(
            f"本次收款超出该期未收金额：应收 {_dec(period.due_amount)} 元，"
            f"已收 {_dec(period.paid_amount)} 元，剩余 {unpaid} 元"
        )

    payment = Payment(
        fee_period_id=period_id,
        amount=payload.amount,
        pay_method=payload.pay_method,
        receipt_no=payload.receipt_no,
        invoice_no=payload.invoice_no,
        invoice_title=payload.invoice_title,
        invoice_status=payload.invoice_status,
        paid_at=payload.paid_at or datetime.now(),
        source="offline",
        created_by=current.id,
    )
    db.add(payment)

    new_paid = _dec(period.paid_amount) + _dec(payload.amount)
    period.paid_amount = new_paid
    period.status = "paid" if new_paid >= _dec(period.due_amount) else "partial"

    await db.commit()
    await db.refresh(payment)
    await db.refresh(period)
    return payment, period


# ---------------------------------------------------------------------------
# 5.1.8 发票信息补录
# ---------------------------------------------------------------------------


async def update_payment_invoice(
    db: AsyncSession, payment_id: int, payload: PaymentInvoiceIn, current: User
) -> Payment:
    """补录/修改收款记录的发票信息。"""
    payment = await db.get(Payment, payment_id)
    if payment is None:
        raise NotFound("收款记录不存在")

    period = await _get_period_or_404(db, payment.fee_period_id)
    await _assert_period_access(db, period, current)

    if payload.invoice_status == "issued" and not (payload.invoice_no or "").strip():
        raise BadRequest("发票状态设为「已开票」时必须填写发票号")

    payment.invoice_no = payload.invoice_no
    payment.invoice_title = payload.invoice_title
    payment.invoice_status = payload.invoice_status

    await db.commit()
    await db.refresh(payment)
    return payment


# ---------------------------------------------------------------------------
# 查询：方案列表 / 详情 / 收款记录
# ---------------------------------------------------------------------------


async def list_fee_plans(
    db: AsyncSession,
    *,
    current: User,
    case_id: int | None = None,
    status: str | None = None,
    keyword: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[int, list[FeePlan]]:
    """分页查询收费方案。

    ``status`` 按期次汇总派生：unpaid 未收 / partial 部分 / paid 已结清 /
    overdue 有逾期未收。
    """
    if page < 1:
        raise BadRequest("页码必须大于等于 1")
    if not 1 <= page_size <= 100:
        raise BadRequest("每页数量需在 1~100 之间")

    today = date.today()
    agg_sub = (
        select(
            FeePeriod.fee_plan_id.label("plan_id"),
            func.coalesce(func.sum(FeePeriod.due_amount), 0).label("due_total"),
            func.coalesce(func.sum(FeePeriod.paid_amount), 0).label("paid_total"),
            func.count(FeePeriod.id).label("period_count"),
            func.coalesce(
                func.sum(
                    case(
                        (
                            and_(
                                FeePeriod.status != "paid",
                                FeePeriod.due_date.is_not(None),
                                FeePeriod.due_date < today,
                            ),
                            FeePeriod.due_amount - FeePeriod.paid_amount,
                        ),
                        else_=0,
                    )
                ),
                0,
            ).label("overdue_amount"),
        )
        .group_by(FeePeriod.fee_plan_id)
        .subquery()
    )

    stmt = (
        select(FeePlan)
        .join(Case, Case.id == FeePlan.case_id)
        .outerjoin(agg_sub, agg_sub.c.plan_id == FeePlan.id)
    )
    stmt = _scope_stmt(stmt, current)

    if case_id:
        stmt = stmt.where(FeePlan.case_id == case_id)
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(or_(Case.title.like(like), Case.case_no.like(like)))

    paid_total = func.coalesce(agg_sub.c.paid_total, 0)
    due_total = func.coalesce(agg_sub.c.due_total, 0)
    if status == "unpaid":
        stmt = stmt.where(paid_total == 0)
    elif status == "partial":
        stmt = stmt.where(paid_total > 0, paid_total < due_total)
    elif status == "paid":
        stmt = stmt.where(due_total > 0, paid_total >= due_total)
    elif status == "overdue":
        stmt = stmt.where(func.coalesce(agg_sub.c.overdue_amount, 0) > 0)
    elif status:
        raise BadRequest("收费状态取值不合法（unpaid/partial/paid/overdue）")

    total = await db.scalar(select(func.count()).select_from(stmt.subquery()))
    rows = (
        (
            await db.execute(
                stmt.order_by(FeePlan.created_at.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    plans = list(rows)
    await _attach_plan_context(db, plans)
    return total or 0, plans


async def get_fee_plan_detail(
    db: AsyncSession, plan_id: int, current: User
) -> tuple[FeePlan, list[FeePeriod]]:
    """方案详情：方案本体 + 期次清单（按期次号升序）。"""
    plan = await _get_plan_or_404(db, plan_id)
    await _assert_case_access(db, plan.case_id, current)
    await _attach_plan_context(db, [plan])

    periods = (
        (
            await db.execute(
                select(FeePeriod)
                .where(FeePeriod.fee_plan_id == plan_id)
                .order_by(FeePeriod.period_no.asc())
            )
        )
        .scalars()
        .all()
    )
    for p in periods:
        p.overdue_days = _overdue_days(p.due_date)
    return plan, list(periods)


async def list_period_payments(
    db: AsyncSession, period_id: int, current: User
) -> list[Payment]:
    """某期次的收款流水（按收款时间倒序）。"""
    period = await _get_period_or_404(db, period_id)
    await _assert_period_access(db, period, current)

    rows = (
        (
            await db.execute(
                select(Payment)
                .where(Payment.fee_period_id == period_id)
                .order_by(Payment.paid_at.desc(), Payment.id.desc())
            )
        )
        .scalars()
        .all()
    )
    return list(rows)


# ---------------------------------------------------------------------------
# 5.1.5 催收清单
# ---------------------------------------------------------------------------


async def list_collect_list(
    db: AsyncSession,
    current: User,
    *,
    min_overdue_days: int = 0,
) -> list[CollectItemOut]:
    """催收清单：应收日期已到（含当天）且尚未结清的期次。

    ``min_overdue_days`` 可过滤掉刚到期未逾期的条目（如传 1 只看逾期）。
    """
    if min_overdue_days < 0:
        raise BadRequest("逾期天数不能为负数")

    today = date.today()
    stmt = (
        select(FeePeriod, FeePlan, Case, ClientProfile.name)
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .join(Case, Case.id == FeePlan.case_id)
        .join(ClientProfile, ClientProfile.id == Case.client_id, isouter=True)
        .where(
            FeePeriod.status != "paid",
            FeePeriod.due_date.is_not(None),
            FeePeriod.due_date <= today,
        )
    )
    stmt = _scope_stmt(stmt, current)

    rows = (
        await db.execute(stmt.order_by(FeePeriod.due_date.asc(), FeePeriod.id.asc()))
    ).all()

    items: list[CollectItemOut] = []
    for period, plan, row_case, client_name in rows:
        overdue = _overdue_days(period.due_date)
        if overdue < min_overdue_days:
            continue
        items.append(
            CollectItemOut(
                period_id=period.id,
                fee_plan_id=plan.id,
                case_id=row_case.id,
                case_no=row_case.case_no,
                case_title=row_case.title,
                client_id=row_case.client_id,
                client_name=client_name,
                period_no=period.period_no,
                due_amount=_dec(period.due_amount),
                paid_amount=_dec(period.paid_amount),
                unpaid_amount=_dec(period.due_amount) - _dec(period.paid_amount),
                due_date=period.due_date,
                overdue_days=overdue,
            )
        )
    return items


# ---------------------------------------------------------------------------
# 5.1.5 营收统计
# ---------------------------------------------------------------------------


async def get_billing_stats(
    db: AsyncSession,
    current: User,
    *,
    year: int | None = None,
    month: int | None = None,
) -> BillingStatsOut:
    """营收统计：当月实收、累计应收/已收/未收、回款率、逾期情况。"""
    today = date.today()
    y = year or today.year
    m = month or today.month
    if not 1 <= m <= 12:
        raise BadRequest("月份需在 1~12 之间")
    if not 2000 <= y <= 2100:
        raise BadRequest("年份取值不合法")

    # 累计应收 / 已收（期次维度）
    due_stmt = select(
        func.coalesce(func.sum(FeePeriod.due_amount), 0),
        func.coalesce(func.sum(FeePeriod.paid_amount), 0),
    ).join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
    due_stmt = _scope_stmt(due_stmt, current)
    total_due_raw, total_paid_raw = (await db.execute(due_stmt)).one()
    total_due = _dec(total_due_raw)
    total_paid = _dec(total_paid_raw)
    total_unpaid = total_due - total_paid

    # 当月实收（收款维度）
    income_stmt = (
        select(func.coalesce(func.sum(Payment.amount), 0))
        .join(FeePeriod, FeePeriod.id == Payment.fee_period_id)
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .where(
            func.year(Payment.paid_at) == y,
            func.month(Payment.paid_at) == m,
        )
    )
    income_stmt = _scope_stmt(income_stmt, current)
    month_income = _dec(await db.scalar(income_stmt))

    # 逾期未收
    overdue_stmt = (
        select(
            func.coalesce(func.sum(FeePeriod.due_amount - FeePeriod.paid_amount), 0),
            func.count(FeePeriod.id),
        )
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .where(
            FeePeriod.status != "paid",
            FeePeriod.due_date.is_not(None),
            FeePeriod.due_date < today,
        )
    )
    overdue_stmt = _scope_stmt(overdue_stmt, current)
    overdue_amount_raw, overdue_count_raw = (await db.execute(overdue_stmt)).one()

    rate = float(total_paid / total_due * 100) if total_due > 0 else 0.0

    return BillingStatsOut(
        month=f"{y:04d}-{m:02d}",
        month_income=month_income,
        total_due=total_due,
        total_paid=total_paid,
        total_unpaid=total_unpaid,
        collection_rate=round(rate, 2),
        overdue_amount=_dec(overdue_amount_raw),
        overdue_count=int(overdue_count_raw or 0),
    )


# ---------------------------------------------------------------------------
# 5.1.7 客户端账单（行级隔离到本人）
# ---------------------------------------------------------------------------


async def list_my_bills(db: AsyncSession, current: User) -> list[BillOut]:
    """客户端：本人委托案件的账单（应收 / 已缴 / 发票状态）。

    归属判定与「我的案件」「我的合同」一致：``client_profile.user_id`` 或
    手机号匹配，双保险兼容律师代录后尚未回填 ``user_id`` 的档案。
    """
    if current.role != "client":
        raise Forbidden("仅客户可查看")

    owner_cond = or_(
        ClientProfile.user_id == current.id,
        ClientProfile.phone == current.phone,
    )
    stmt = (
        select(FeePeriod, FeePlan, Case)
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .join(Case, Case.id == FeePlan.case_id)
        .join(ClientProfile, ClientProfile.id == Case.client_id)
        .where(owner_cond)
        .order_by(
            FeePeriod.due_date.is_(None),
            FeePeriod.due_date.asc(),
            FeePeriod.period_no.asc(),
        )
    )
    rows = (await db.execute(stmt)).all()

    # 批量取每期次的收款信息：最新收款时间 + 已开票情况 + 最新一笔收款来源
    period_ids = [period.id for period, _, _ in rows]
    invoice_map: dict[int, tuple[str, str | None, datetime]] = {}
    last_source_map: dict[int, str] = {}
    if period_ids:
        pay_rows = (
            await db.execute(
                select(
                    Payment.fee_period_id,
                    Payment.invoice_status,
                    Payment.invoice_no,
                    Payment.paid_at,
                    Payment.source,
                )
                .where(Payment.fee_period_id.in_(period_ids))
                .order_by(Payment.paid_at.desc(), Payment.id.desc())
            )
        ).all()
        # 一期可能多次收款：paid_at 取最新一笔；发票取优先级最高的那笔
        # （issued > applied > none），避免"先开票后现金收款"把已开票信息盖掉
        for pid, inv_status, inv_no, paid_at, source in pay_rows:
            last_source_map.setdefault(pid, source)
            current = invoice_map.get(pid)
            if current is None:
                invoice_map[pid] = (inv_status, inv_no, paid_at)
            elif _invoice_priority(inv_status) > _invoice_priority(current[0]):
                invoice_map[pid] = (inv_status, inv_no, current[2])

    bills: list[BillOut] = []
    for period, plan, row_case in rows:
        inv_status, inv_no, last_paid_at = invoice_map.get(
            period.id, ("none", None, None)
        )
        bills.append(
            BillOut(
                period_id=period.id,
                fee_plan_id=plan.id,
                case_id=row_case.id,
                case_no=row_case.case_no,
                case_title=row_case.title,
                fee_type=plan.fee_type,
                period_no=period.period_no,
                due_amount=_dec(period.due_amount),
                paid_amount=_dec(period.paid_amount),
                unpaid_amount=_dec(period.due_amount) - _dec(period.paid_amount),
                due_date=period.due_date,
                status=period.status,
                overdue_days=_overdue_days(period.due_date),
                invoice_status=inv_status,
                invoice_no=inv_no,
                paid_at=last_paid_at,
                last_pay_source=last_source_map.get(period.id),
            )
        )
    return bills
