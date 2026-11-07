"""沙箱支付订单模型。

客户在账单页发起在线缴费时先生成一条订单，沙箱网关确认后把订单置为
``paid`` 并写入一条 ``payment`` 收款记录。这样律师端、管理员端的收费台账
与统计都能直接复用收款表，实现三端数据一致。

状态机：``pending`` → ``paid`` / ``failed`` / ``cancelled`` / ``expired``。
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class PaymentOrder(Base):
    """沙箱支付订单。"""

    __tablename__ = "payment_order"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    order_no: Mapped[str] = mapped_column(
        String(40), nullable=False, unique=True, comment="商户订单号"
    )
    fee_period_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="所属收费期次"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, comment="应付金额"
    )
    channel: Mapped[str] = mapped_column(
        String(16), nullable=False, comment="支付渠道：wechat/alipay/bank"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "pending",
            "paid",
            "failed",
            "cancelled",
            "expired",
            name="payment_order_status",
        ),
        nullable=False,
        default="pending",
        comment="待支付/已支付/失败/已取消/已过期",
    )
    payer_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="发起支付的客户用户ID"
    )
    transaction_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="沙箱网关交易号"
    )
    payment_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="支付成功生成的收款记录ID"
    )
    fail_reason: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="失败/过期原因"
    )
    expired_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="订单过期时间"
    )
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="支付成功时间"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 非数据库字段：service 层注入，供列表/详情展示。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    case_id = None
    case_no = None
    case_title = None
    client_name = None
    period_no = None
    fee_plan_id = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<PaymentOrder {self.order_no} {self.status} {self.amount}>"
