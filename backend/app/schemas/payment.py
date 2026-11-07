"""沙箱支付相关的请求/响应模型。

沙箱支付用「下单 → 模拟网关确认 → 落收款记录」三步模拟真实在线支付，
订单状态机与真实渠道一致，便于后续替换为微信/支付宝正式接口。
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from app.schemas.billing import MAX_AMOUNT, FeePeriodOut, PaymentOut

# 支持的支付渠道（沙箱）
PAY_CHANNELS = ("wechat", "alipay", "bank")

CHANNEL_LABELS = {
    "wechat": "微信支付",
    "alipay": "支付宝",
    "bank": "银行卡",
}

ORDER_STATUS_LABELS = {
    "pending": "待支付",
    "paid": "已支付",
    "failed": "支付失败",
    "cancelled": "已取消",
    "expired": "已过期",
}


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------


class PaymentOrderIn(BaseModel):
    """创建支付订单：金额缺省为当期剩余待缴金额。"""

    amount: Decimal | None = Field(
        default=None, gt=0, le=MAX_AMOUNT, description="缴费金额，缺省为待缴全额"
    )
    channel: str = Field(
        default="wechat",
        pattern="^(wechat|alipay|bank)$",
        description="支付渠道：wechat/alipay/bank",
    )


class SandboxPayIn(BaseModel):
    """沙箱支付确认（模拟网关回调）。"""

    result: str = Field(
        default="success",
        pattern="^(success|failed)$",
        description="模拟结果：success 支付成功 / failed 支付失败",
    )
    reason: str | None = Field(
        default=None, max_length=200, description="失败原因，仅 result=failed 时展示"
    )


# ---------------------------------------------------------------------------
# 输出模型
# ---------------------------------------------------------------------------


class PaymentOrderOut(BaseModel):
    """支付订单输出（收银台 / 律师端对账共用）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    order_no: str
    fee_period_id: int
    amount: Decimal
    channel: str
    status: str
    transaction_no: str | None = None
    payment_id: int | None = None
    fail_reason: str | None = None
    expired_at: datetime
    paid_at: datetime | None = None
    created_at: datetime

    # 由 service 注入，便于列表直接展示归属
    case_id: int | None = None
    case_no: str | None = None
    case_title: str | None = None
    client_name: str | None = None
    period_no: int | None = None
    fee_plan_id: int | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def channel_label(self) -> str:
        return CHANNEL_LABELS.get(self.channel, self.channel)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def status_label(self) -> str:
        return ORDER_STATUS_LABELS.get(self.status, self.status)


class PaymentOrderPayOut(BaseModel):
    """沙箱支付结果：订单状态 + 成功时生成的收款记录与期次最新状态。"""

    order: PaymentOrderOut
    payment: PaymentOut | None = None
    period: FeePeriodOut | None = None
