"""收费管理相关的请求/响应模型。

覆盖：收费方案（含分期）、收费期次、收款登记（含发票信息）、
催收清单、账单视图与营收统计。
"""

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# 收费方式枚举（与 DB ENUM 一致）
FEE_TYPES = ("fixed", "ratio", "risk", "hourly")
# 期次状态
FEE_PERIOD_STATUSES = ("unpaid", "partial", "paid")
# 发票状态
INVOICE_STATUSES = ("none", "applied", "issued")

# 金额上限：与数据库 DECIMAL(12,2) 对齐（12 位有效数字，2 位小数）
MAX_AMOUNT = Decimal("9999999999.99")

# 期次应收合计与方案总额的允许误差（元）
AMOUNT_TOLERANCE = Decimal("0.01")


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class FeePeriodIn(BaseModel):
    """收费期次入参（创建方案时随附，或单独追加期次）。"""

    period_no: int | None = Field(
        default=None, ge=1, le=99, description="期次序号，缺省按顺序自动生成"
    )
    due_amount: Decimal = Field(
        ge=0, le=MAX_AMOUNT, description="应收金额（元）"
    )
    due_date: date | None = Field(default=None, description="应收日期")

    @field_validator("due_amount")
    @classmethod
    def _check_due_amount(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("期次应收金额必须大于 0")
        return v


class FeePlanIn(BaseModel):
    """收费方案入参。

    ``periods`` 为空时自动生成单期（应收 = 收费总额）；
    非空时要求各期应收合计等于 ``total_amount``。
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    case_id: int = Field(description="关联案件ID")
    fee_type: str = Field(
        default="fixed",
        pattern="^(fixed|ratio|risk|hourly)$",
        description="收费方式：fixed/ratio/risk/hourly",
    )
    total_amount: Decimal = Field(
        gt=0, le=MAX_AMOUNT, description="收费总额（元）"
    )
    description: str | None = Field(default=None, max_length=500, description="收费说明")
    periods: list[FeePeriodIn] = Field(
        default_factory=list, description="分期计划，为空则自动单期"
    )

    @field_validator("periods")
    @classmethod
    def _check_periods_total(
        cls, v: list[FeePeriodIn], info
    ) -> list[FeePeriodIn]:
        """校验各期次应收合计与收费总额一致。"""
        if not v:
            return v
        total = info.data.get("total_amount")
        if total is None:
            return v
        # 期次序号重复会破坏"首期/二期/尾款"的语义
        nos = [p.period_no for p in v if p.period_no is not None]
        if len(nos) != len(set(nos)):
            raise ValueError("期次序号不能重复")
        diff = sum((p.due_amount for p in v), Decimal(0)) - total
        if abs(diff) > AMOUNT_TOLERANCE:
            raise ValueError("各期次应收合计与收费总额不一致，请核对分期金额")
        return v


class PaymentIn(BaseModel):
    """收款登记入参（支持部分收款）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    amount: Decimal = Field(gt=0, le=MAX_AMOUNT, description="本次实收金额（元）")
    pay_method: str | None = Field(
        default=None, max_length=32, description="银行转账/现金/微信/支付宝"
    )
    receipt_no: str | None = Field(default=None, max_length=64, description="收据号")
    paid_at: datetime | None = Field(
        default=None, description="收款时间，缺省为当前时间"
    )
    invoice_no: str | None = Field(default=None, max_length=64, description="发票号")
    invoice_title: str | None = Field(
        default=None, max_length=255, description="开票抬头"
    )
    invoice_status: str = Field(
        default="none",
        pattern="^(none|applied|issued)$",
        description="发票状态：none/applied/issued",
    )


class PaymentInvoiceIn(BaseModel):
    """发票信息补录入参（收款后单独登记发票）。"""

    model_config = ConfigDict(str_strip_whitespace=True)

    invoice_no: str | None = Field(default=None, max_length=64, description="发票号")
    invoice_title: str | None = Field(
        default=None, max_length=255, description="开票抬头"
    )
    invoice_status: str = Field(
        default="none",
        pattern="^(none|applied|issued)$",
        description="发票状态：none/applied/issued",
    )


# ---------------------------------------------------------------------------
# 输出模型
# ---------------------------------------------------------------------------


class PaymentOut(BaseModel):
    """收款记录输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_period_id: int
    amount: Decimal
    pay_method: str | None = None
    receipt_no: str | None = None
    invoice_no: str | None = None
    invoice_title: str | None = None
    invoice_status: str
    paid_at: datetime
    source: str = "offline"
    order_no: str | None = None
    created_by: int | None = None
    created_at: datetime


class FeePeriodOut(BaseModel):
    """收费期次输出。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    fee_plan_id: int
    period_no: int
    due_amount: Decimal
    paid_amount: Decimal
    unpaid_amount: Decimal = Decimal("0.00")
    due_date: date | None = None
    status: str
    overdue_days: int = 0
    created_at: datetime


class PaymentResultOut(BaseModel):
    """收款登记结果：本次收款记录 + 期次最新状态（便于前端直接刷新状态）。"""

    payment: PaymentOut
    period: FeePeriodOut


class FeePlanOut(BaseModel):
    """收费方案输出（列表行）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    case_no: str | None = None
    case_title: str | None = None
    client_id: int | None = None
    client_name: str | None = None
    fee_type: str
    total_amount: Decimal
    due_total: Decimal | None = None
    paid_total: Decimal | None = None
    period_count: int | None = None
    description: str | None = None
    created_at: datetime


class FeePlanDetailOut(FeePlanOut):
    """收费方案详情（含期次清单）。"""

    periods: list[FeePeriodOut] = Field(default_factory=list)
    # 客户正在进行中的在线支付（律师端据此提示"客户支付中"）
    pending_order_count: int = 0
    pending_order_amount: Decimal = Decimal("0.00")


class FeePlanListOut(BaseModel):
    """收费方案分页列表输出。"""

    total: int
    items: list[FeePlanOut]


class BillOut(BaseModel):
    """客户端账单输出（按期次的账单视图）。"""

    period_id: int
    fee_plan_id: int
    case_id: int
    case_no: str | None = None
    case_title: str | None = None
    fee_type: str | None = None
    period_no: int
    due_amount: Decimal
    paid_amount: Decimal
    unpaid_amount: Decimal
    due_date: date | None = None
    status: str
    overdue_days: int = 0
    invoice_status: str = "none"
    invoice_no: str | None = None
    paid_at: datetime | None = None
    last_pay_source: str | None = None


class CollectItemOut(BaseModel):
    """催收清单条目（已到期未结清）。"""

    period_id: int
    fee_plan_id: int
    case_id: int
    case_no: str | None = None
    case_title: str | None = None
    client_id: int | None = None
    client_name: str | None = None
    period_no: int
    due_amount: Decimal
    paid_amount: Decimal
    unpaid_amount: Decimal
    due_date: date | None = None
    overdue_days: int = 0


class BillingStatsOut(BaseModel):
    """营收统计输出。"""

    month: str = Field(description="统计月份，格式 YYYY-MM")
    month_income: Decimal = Field(description="当月实收金额")
    total_due: Decimal = Field(description="累计应收金额")
    total_paid: Decimal = Field(description="累计已收金额")
    total_unpaid: Decimal = Field(description="累计未收金额")
    collection_rate: float = Field(description="回款率（百分比，保留两位小数）")
    overdue_amount: Decimal = Field(description="逾期未收金额")
    overdue_count: int = Field(description="逾期期次数量")
