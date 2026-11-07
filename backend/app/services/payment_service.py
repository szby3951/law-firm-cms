"""沙箱支付业务逻辑。

链路：客户发起缴费 → 生成 ``payment_order`` → 沙箱网关确认 → 写入
``payment`` 收款记录并联动期次状态。

之所以把支付结果落在 ``payment`` 表，是为了让律师端、管理员端的收费台账、
营收统计、催收清单与客户端账单共用同一份数据，避免"支付成功了但台账没变"。

沙箱说明：不接真实商户号，确认动作由前端「模拟支付」按钮触发，
交易号以 ``MOCK`` 开头，便于与真实渠道区分。
"""

import secrets
from datetime import datetime, timedelta
from decimal import Decimal

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequest, Forbidden, NotFound
from app.models.billing import FeePeriod, FeePlan, Payment
from app.models.case import Case
from app.models.case_lawyer import CaseLawyer
from app.models.client import ClientProfile
from app.models.payment_order import PaymentOrder
from app.models.user import User
from app.schemas.billing import AMOUNT_TOLERANCE
from app.schemas.payment import CHANNEL_LABELS, ORDER_STATUS_LABELS, PaymentOrderIn

ZERO = Decimal("0.00")
# 订单有效期：30 分钟未支付自动过期
ORDER_TTL = timedelta(minutes=30)


def _dec(value) -> Decimal:
    if value is None:
        return ZERO
    return value if isinstance(value, Decimal) else Decimal(str(value))


def _new_order_no() -> str:
    """商户订单号：PAY + 秒级时间 + 6 位随机，长度 23。"""
    return f"PAY{datetime.now():%Y%m%d%H%M%S}{secrets.randbelow(900000) + 100000}"


def _mock_transaction_no() -> str:
    """沙箱交易号：MOCK 前缀，一眼可辨不是真实渠道流水。"""
    return f"MOCK{datetime.now():%Y%m%d%H%M%S}{secrets.randbelow(9000) + 1000}"


def _order_status_label(status: str) -> str:
    return ORDER_STATUS_LABELS.get(status, status)


# ---------------------------------------------------------------------------
# 权限与上下文
# ---------------------------------------------------------------------------


async def _get_period_or_404(db: AsyncSession, period_id: int) -> FeePeriod:
    period = await db.get(FeePeriod, period_id)
    if period is None:
        raise NotFound("收费期次不存在")
    return period


async def _assert_client_owns_period(
    db: AsyncSession, period: FeePeriod, current: User
) -> None:
    """客户端只能为本人委托案件的账单缴费（行级隔离）。"""
    if current.role != "client":
        raise Forbidden("仅客户可发起在线缴费")
    owned = await db.scalar(
        select(FeePeriod.id)
        .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
        .join(Case, Case.id == FeePlan.case_id)
        .join(ClientProfile, ClientProfile.id == Case.client_id)
        .where(
            FeePeriod.id == period.id,
            or_(
                ClientProfile.user_id == current.id,
                ClientProfile.phone == current.phone,
            ),
        )
    )
    if owned is None:
        raise Forbidden("无权为该账单缴费")


async def _assert_staff_access(
    db: AsyncSession, case_id: int, current: User
) -> None:
    """律师/管理员查看支付订单的案件权限，与收费模块保持一致。"""
    if current.role == "admin":
        return
    if current.role != "lawyer":
        raise Forbidden("无权查看该支付订单")
    lawyer_ids = (
        (
            await db.execute(
                select(CaseLawyer.lawyer_id).where(CaseLawyer.case_id == case_id)
            )
        )
        .scalars()
        .all()
    )
    if current.id not in set(lawyer_ids):
        raise Forbidden("只能查看本人承办案件的支付订单")


async def _attach_order_context(
    db: AsyncSession, orders: list[PaymentOrder]
) -> list[PaymentOrder]:
    """批量注入案件号/标题、客户、期次号，供收银台与对账列表展示。"""
    if not orders:
        return orders

    period_ids = {o.fee_period_id for o in orders}
    rows = (
        await db.execute(
            select(
                FeePeriod.id,
                FeePeriod.period_no,
                FeePeriod.fee_plan_id,
                FeePlan.case_id,
                Case.case_no,
                Case.title,
                ClientProfile.name,
            )
            .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
            .join(Case, Case.id == FeePlan.case_id)
            .outerjoin(ClientProfile, ClientProfile.id == Case.client_id)
            .where(FeePeriod.id.in_(period_ids))
        )
    ).all()
    ctx = {
        pid: (period_no, plan_id, case_id, case_no, title, client_name)
        for pid, period_no, plan_id, case_id, case_no, title, client_name in rows
    }

    for order in orders:
        period_no, plan_id, case_id, case_no, title, client_name = ctx.get(
            order.fee_period_id, (None, None, None, None, None, None)
        )
        order.period_no = period_no
        order.fee_plan_id = plan_id
        order.case_id = case_id
        order.case_no = case_no
        order.case_title = title
        order.client_name = client_name
    return orders


async def _expire_stale(
    db: AsyncSession, *, plan_id: int | None = None
) -> None:
    """把超时未支付的订单置为 expired（惰性清理，避免定时任务）。"""
    stmt = update(PaymentOrder).where(
        PaymentOrder.status == "pending",
        PaymentOrder.expired_at <= datetime.now(),
    )
    if plan_id is not None:
        stmt = stmt.where(
            PaymentOrder.fee_period_id.in_(
                select(FeePeriod.id).where(FeePeriod.fee_plan_id == plan_id)
            )
        )
    await db.execute(stmt.values(status="expired", fail_reason="订单超时未支付"))


# ---------------------------------------------------------------------------
# 下单
# ---------------------------------------------------------------------------


async def create_order(
    db: AsyncSession, period_id: int, payload: PaymentOrderIn, current: User
) -> PaymentOrder:
    """为某一期账单创建支付订单。

    - 金额缺省为当期剩余待缴金额；允许部分缴费。
    - 同一客户同一期次已有**同额且未过期**的待支付订单时直接复用，
      避免重复点击生成一堆订单。
    """
    period = await _get_period_or_404(db, period_id)
    await _assert_client_owns_period(db, period, current)

    unpaid = _dec(period.due_amount) - _dec(period.paid_amount)
    if unpaid <= 0 or period.status == "paid":
        raise BadRequest("该期账单已结清，无需缴费")

    amount = payload.amount if payload.amount is not None else unpaid
    if amount <= 0:
        raise BadRequest("缴费金额必须大于 0")
    if amount - unpaid > AMOUNT_TOLERANCE:
        raise BadRequest(f"缴费金额超出待缴金额，当前待缴 {unpaid} 元")

    now = datetime.now()
    await _expire_stale(db)

    # 处理该期次已有的待支付订单：同额复用，异额取消
    pendings = (
        (
            await db.execute(
                select(PaymentOrder).where(
                    PaymentOrder.fee_period_id == period_id,
                    PaymentOrder.payer_id == current.id,
                    PaymentOrder.status == "pending",
                )
            )
        )
        .scalars()
        .all()
    )
    for old in pendings:
        if _dec(old.amount) == _dec(amount):
            await _attach_order_context(db, [old])
            return old
        old.status = "cancelled"
        old.fail_reason = "客户重新发起支付，原订单已取消"

    # 订单号极小概率碰撞，生成时做一次存在性检查
    for _ in range(5):
        order_no = _new_order_no()
        exists = await db.scalar(
            select(PaymentOrder.id).where(PaymentOrder.order_no == order_no)
        )
        if exists is None:
            break
    else:  # pragma: no cover - 理论上不会走到
        raise BadRequest("订单号生成失败，请重试")

    order = PaymentOrder(
        order_no=order_no,
        fee_period_id=period_id,
        amount=amount,
        channel=payload.channel,
        status="pending",
        payer_id=current.id,
        expired_at=now + ORDER_TTL,
    )
    db.add(order)
    await db.commit()
    await db.refresh(order)
    await _attach_order_context(db, [order])
    return order


# ---------------------------------------------------------------------------
# 沙箱支付确认
# ---------------------------------------------------------------------------


async def sandbox_pay(
    db: AsyncSession,
    order_no: str,
    result: str,
    reason: str | None,
    current: User,
) -> tuple[PaymentOrder, Payment | None, FeePeriod | None]:
    """模拟网关确认支付。

    - ``success``：写收款记录、累加期次已收、联动状态，订单置 paid。
    - ``failed``：订单置 failed，不产生任何收款记录。
    - 已支付订单重复确认时幂等返回原结果，不会重复入账。
    """
    if current.role != "client":
        raise Forbidden("仅客户可发起在线缴费")

    order = (
        await db.execute(
            select(PaymentOrder)
            .where(PaymentOrder.order_no == order_no)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None:
        raise NotFound("支付订单不存在")
    if order.payer_id != current.id:
        raise NotFound("支付订单不存在")

    # 幂等：已支付直接返回原收款记录
    if order.status == "paid":
        payment = (
            await db.get(Payment, order.payment_id) if order.payment_id else None
        )
        period = await db.get(FeePeriod, order.fee_period_id)
        await _attach_order_context(db, [order])
        return order, payment, period

    if order.status != "pending":
        raise BadRequest(
            f"订单{_order_status_label(order.status)}，请重新发起支付"
        )

    now = datetime.now()
    if order.expired_at <= now:
        order.status = "expired"
        order.fail_reason = "订单超时未支付"
        await db.commit()
        raise BadRequest("订单已超时，请重新发起支付")

    # 模拟失败：不落收款记录，便于演示重试与对账
    if result == "failed":
        order.status = "failed"
        order.fail_reason = reason or "沙箱模拟：渠道返回失败（余额不足或用户取消支付）"
        await db.commit()
        await db.refresh(order)
        await _attach_order_context(db, [order])
        return order, None, None

    # 成功：锁期次后校验剩余金额，防止与律师线下登记收款并发冲突
    period = (
        await db.execute(
            select(FeePeriod)
            .where(FeePeriod.id == order.fee_period_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if period is None:
        order.status = "failed"
        order.fail_reason = "收费期次不存在或已删除"
        await db.commit()
        raise NotFound("收费期次不存在")

    unpaid = _dec(period.due_amount) - _dec(period.paid_amount)
    if unpaid <= 0 or period.status == "paid":
        order.status = "failed"
        order.fail_reason = "该期账单已结清（可能已通过线下方式缴纳）"
        await db.commit()
        raise BadRequest("该期账单已结清，本次支付已关闭，请刷新账单查看")
    if _dec(order.amount) - unpaid > AMOUNT_TOLERANCE:
        order.status = "failed"
        order.fail_reason = (
            f"账单剩余待缴金额不足（当前剩余 {unpaid} 元），请重新发起支付"
        )
        await db.commit()
        raise BadRequest(order.fail_reason)

    payment = Payment(
        fee_period_id=period.id,
        amount=_dec(order.amount),
        pay_method=CHANNEL_LABELS.get(order.channel, order.channel),
        receipt_no=order.order_no,
        invoice_status="none",
        paid_at=now,
        source="online",
        order_no=order.order_no,
        created_by=current.id,
    )
    db.add(payment)
    await db.flush()

    new_paid = _dec(period.paid_amount) + _dec(order.amount)
    period.paid_amount = new_paid
    period.status = "paid" if new_paid >= _dec(period.due_amount) else "partial"

    order.status = "paid"
    order.transaction_no = _mock_transaction_no()
    order.payment_id = payment.id
    order.paid_at = now

    await db.commit()
    await db.refresh(payment)
    await db.refresh(period)
    await db.refresh(order)
    await _attach_order_context(db, [order])
    return order, payment, period


async def cancel_order(
    db: AsyncSession, order_no: str, current: User
) -> PaymentOrder:
    """客户主动取消待支付订单。"""
    if current.role != "client":
        raise Forbidden("仅客户可取消支付订单")

    order = (
        await db.execute(
            select(PaymentOrder)
            .where(PaymentOrder.order_no == order_no)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if order is None or order.payer_id != current.id:
        raise NotFound("支付订单不存在")
    if order.status == "paid":
        raise BadRequest("订单已支付，无法取消")
    if order.status != "pending":
        raise BadRequest(f"订单{_order_status_label(order.status)}，无需取消")

    order.status = "cancelled"
    order.fail_reason = "客户主动取消"
    await db.commit()
    await db.refresh(order)
    await _attach_order_context(db, [order])
    return order


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------


async def get_order(
    db: AsyncSession, order_no: str, current: User
) -> PaymentOrder:
    """按订单号查询：客户仅本人订单，律师/管理员按案件范围。"""
    order = await db.scalar(
        select(PaymentOrder).where(PaymentOrder.order_no == order_no)
    )
    if order is None:
        raise NotFound("支付订单不存在")

    if current.role == "client":
        if order.payer_id != current.id:
            raise NotFound("支付订单不存在")
    else:
        period = await db.get(FeePeriod, order.fee_period_id)
        if period is None:
            raise NotFound("支付订单不存在")
        plan = await db.get(FeePlan, period.fee_plan_id)
        if plan is None:
            raise NotFound("支付订单不存在")
        await _assert_staff_access(db, plan.case_id, current)

    await _expire_stale(db)
    await _attach_order_context(db, [order])
    return order


async def list_orders(
    db: AsyncSession,
    current: User,
    *,
    plan_id: int | None = None,
    period_id: int | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[PaymentOrder]:
    """支付订单列表（律师端对账用）。

    律师仅见本人承办案件；管理员见全所；客户仅见自己的订单。
    """
    if status and status not in (
        "pending",
        "paid",
        "failed",
        "cancelled",
        "expired",
    ):
        raise BadRequest("订单状态取值不合法")
    if not 1 <= limit <= 200:
        raise BadRequest("每页数量需在 1~200 之间")

    await _expire_stale(db)

    stmt = select(PaymentOrder)
    if plan_id is not None or period_id is not None:
        stmt = stmt.join(
            FeePeriod, FeePeriod.id == PaymentOrder.fee_period_id
        )
    if plan_id is not None:
        stmt = stmt.where(FeePeriod.fee_plan_id == plan_id)
    if period_id is not None:
        stmt = stmt.where(PaymentOrder.fee_period_id == period_id)

    if current.role == "client":
        stmt = stmt.where(PaymentOrder.payer_id == current.id)
    elif current.role == "lawyer":
        stmt = stmt.where(
            PaymentOrder.fee_period_id.in_(
                select(FeePeriod.id)
                .join(FeePlan, FeePlan.id == FeePeriod.fee_plan_id)
                .where(
                    FeePlan.case_id.in_(
                        select(CaseLawyer.case_id).where(
                            CaseLawyer.lawyer_id == current.id
                        )
                    )
                )
            )
        )
    elif current.role != "admin":
        raise Forbidden("无权查看支付订单")

    if status:
        stmt = stmt.where(PaymentOrder.status == status)

    rows = (
        (
            await db.execute(
                stmt.order_by(PaymentOrder.created_at.desc()).limit(limit)
            )
        )
        .scalars()
        .all()
    )
    orders = list(rows)
    await _attach_order_context(db, orders)
    return orders


async def pending_order_summary(
    db: AsyncSession, plan_id: int
) -> tuple[int, Decimal]:
    """某方案下进行中的在线支付（供律师端提示"客户支付中"）。"""
    await _expire_stale(db, plan_id=plan_id)
    row = (
        await db.execute(
            select(
                func.count(PaymentOrder.id),
                func.coalesce(func.sum(PaymentOrder.amount), 0),
            )
            .join(FeePeriod, FeePeriod.id == PaymentOrder.fee_period_id)
            .where(
                FeePeriod.fee_plan_id == plan_id,
                PaymentOrder.status == "pending",
            )
        )
    ).one()
    return int(row[0] or 0), _dec(row[1])
