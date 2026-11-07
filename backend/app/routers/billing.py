"""收费管理路由：收费方案、分期期次、收款登记、催收清单、营收统计。

权限约定：律师仅能管理本人承办案件的收费，管理员可操作全所数据；
客户只读，通过 ``/api/my/bills`` 查看本人账单，并通过 ``/api/my/bills/{id}``
下的支付订单接口在线缴费。
"""

from fastapi import APIRouter, Query, Request

from app.core.exceptions import BadRequest
from app.dependencies import CurrentUser, DbSession, client_ip
from app.schemas.billing import (
    BillingStatsOut,
    CollectItemOut,
    FeePeriodIn,
    FeePeriodOut,
    FeePlanDetailOut,
    FeePlanIn,
    FeePlanListOut,
    FeePlanOut,
    PaymentIn,
    PaymentInvoiceIn,
    PaymentOut,
    PaymentResultOut,
)
from app.schemas.payment import PaymentOrderOut
from app.services import audit_service, billing_service, payment_service

router = APIRouter()


def _period_out(period) -> FeePeriodOut:
    """期次输出（未收金额、逾期天数由 service 统一补算）。"""
    return billing_service.to_period_out(period)


# ---------------------------------------------------------------------------
# 收费方案
# ---------------------------------------------------------------------------


@router.get("/plans", response_model=FeePlanListOut, summary="收费方案列表")
async def list_fee_plans(
    db: DbSession,
    user: CurrentUser,
    case_id: int | None = Query(default=None, description="按案件筛选"),
    status: str | None = Query(
        default=None, description="收费状态：unpaid/partial/paid/overdue"
    ),
    keyword: str | None = Query(default=None, description="案件标题/案号模糊搜索"),
    page: int = Query(default=1, ge=1, description="页码"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页数量"),
) -> FeePlanListOut:
    """分页查询收费方案，律师仅见本人承办案件，管理员见全所。"""
    total, items = await billing_service.list_fee_plans(
        db,
        current=user,
        case_id=case_id,
        status=status,
        keyword=keyword,
        page=page,
        page_size=page_size,
    )
    return FeePlanListOut(
        total=total, items=[FeePlanOut.model_validate(x) for x in items]
    )


@router.post("/plans", response_model=FeePlanDetailOut, summary="创建收费方案")
async def create_fee_plan(
    payload: FeePlanIn, request: Request, db: DbSession, user: CurrentUser
) -> FeePlanDetailOut:
    """创建收费方案并按分期计划生成期次（不传 periods 则自动单期）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")

    plan = await billing_service.create_fee_plan(db, payload, user)
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"fee_plan:{plan.id}",
        detail=f"新增收费方案（案件 {plan.case_id}，总额 {plan.total_amount}）",
        ip=client_ip(request),
    )

    plan, periods = await billing_service.get_fee_plan_detail(db, plan.id, user)
    detail = FeePlanDetailOut.model_validate(plan)
    detail.periods = [_period_out(p) for p in periods]
    return detail


@router.get("/plans/{plan_id}", response_model=FeePlanDetailOut, summary="收费方案详情")
async def get_fee_plan(
    plan_id: int, db: DbSession, user: CurrentUser
) -> FeePlanDetailOut:
    """方案详情：基本信息 + 期次清单（含未收金额、逾期天数）。"""
    plan, periods = await billing_service.get_fee_plan_detail(db, plan_id, user)
    detail = FeePlanDetailOut.model_validate(plan)
    detail.periods = [_period_out(p) for p in periods]
    # 客户正在支付的订单，供律师端提示"客户支付中"
    (
        detail.pending_order_count,
        detail.pending_order_amount,
    ) = await payment_service.pending_order_summary(db, plan_id)
    return detail


@router.post(
    "/plans/{plan_id}/periods",
    response_model=FeePeriodOut,
    summary="追加收费期次",
)
async def add_fee_period(
    plan_id: int, payload: FeePeriodIn, db: DbSession, user: CurrentUser
) -> FeePeriodOut:
    """向已有方案追加一期，方案总额自动同步为各期应收合计。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")
    period = await billing_service.add_fee_period(db, plan_id, payload, user)
    return _period_out(period)


# ---------------------------------------------------------------------------
# 收款登记 与 发票
# ---------------------------------------------------------------------------


@router.get(
    "/periods/{period_id}/payments",
    response_model=list[PaymentOut],
    summary="期次收款流水",
)
async def list_period_payments(
    period_id: int, db: DbSession, user: CurrentUser
) -> list[PaymentOut]:
    """某期次的收款记录（按收款时间倒序）。"""
    payments = await billing_service.list_period_payments(db, period_id, user)
    return [PaymentOut.model_validate(p) for p in payments]


@router.post(
    "/periods/{period_id}/payments",
    response_model=PaymentResultOut,
    summary="登记收款",
)
async def register_payment(
    period_id: int,
    payload: PaymentIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> PaymentResultOut:
    """登记一笔收款；累计实收自动联动期次状态（部分收款 / 结清）。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")

    payment, period = await billing_service.register_payment(
        db, period_id, payload, user
    )
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_CREATE,
        target=f"payment:{payment.id}",
        detail=f"登记收款 {payment.amount} 元（期次 {period_id}）",
        ip=client_ip(request),
    )
    return PaymentResultOut(
        payment=PaymentOut.model_validate(payment),
        period=_period_out(period),
    )


@router.patch(
    "/payments/{payment_id}/invoice",
    response_model=PaymentOut,
    summary="登记/修改发票信息",
)
async def update_payment_invoice(
    payment_id: int,
    payload: PaymentInvoiceIn,
    request: Request,
    db: DbSession,
    user: CurrentUser,
) -> PaymentOut:
    """收款后补录发票号、开票抬头与开票状态。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权操作")

    payment = await billing_service.update_payment_invoice(
        db, payment_id, payload, user
    )
    await audit_service.write_log_safe(
        db,
        user_id=user.id,
        action=audit_service.ACTION_UPDATE,
        target=f"payment:{payment.id}",
        detail=f"登记发票（{payload.invoice_status}"
        f"{'，' + payload.invoice_no if payload.invoice_no else ''}）",
        ip=client_ip(request),
    )
    return PaymentOut.model_validate(payment)


# ---------------------------------------------------------------------------
# 在线支付订单（三端对账）
# ---------------------------------------------------------------------------


@router.get(
    "/orders",
    response_model=list[PaymentOrderOut],
    summary="支付订单列表",
)
async def list_payment_orders(
    db: DbSession,
    user: CurrentUser,
    plan_id: int | None = Query(default=None, description="按收费方案筛选"),
    period_id: int | None = Query(default=None, description="按期次筛选"),
    status: str | None = Query(
        default=None,
        description="订单状态：pending/paid/failed/cancelled/expired",
    ),
    limit: int = Query(default=50, ge=1, le=200, description="返回条数"),
) -> list[PaymentOrderOut]:
    """客户在线支付订单，律师端用于核对"客户是否真的付了钱"。

    律师仅见本人承办案件，管理员见全所，客户仅见自己的订单。
    """
    orders = await payment_service.list_orders(
        db,
        user,
        plan_id=plan_id,
        period_id=period_id,
        status=status,
        limit=limit,
    )
    return [PaymentOrderOut.model_validate(o) for o in orders]


# ---------------------------------------------------------------------------
# 催收清单 与 统计
# ---------------------------------------------------------------------------


@router.get(
    "/collect-list", response_model=list[CollectItemOut], summary="催收清单"
)
async def collect_list(
    db: DbSession,
    user: CurrentUser,
    min_overdue_days: int = Query(
        default=0, ge=0, le=3650, description="最小逾期天数，0 表示含当天到期"
    ),
) -> list[CollectItemOut]:
    """已到期未结清的期次清单（按应收日期升序）。"""
    return await billing_service.list_collect_list(
        db, user, min_overdue_days=min_overdue_days
    )


@router.get("/stats", response_model=BillingStatsOut, summary="营收统计")
async def billing_stats(
    db: DbSession,
    user: CurrentUser,
    year: int | None = Query(default=None, ge=2000, le=2100, description="年份"),
    month: int | None = Query(default=None, ge=1, le=12, description="月份"),
) -> BillingStatsOut:
    """营收统计：当月实收、累计应收/已收/未收、回款率、逾期情况。"""
    if user.role not in ("lawyer", "admin"):
        raise BadRequest("无权查看营收统计")
    return await billing_service.get_billing_stats(db, user, year=year, month=month)
