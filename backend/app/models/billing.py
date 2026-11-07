"""收费管理 ORM 模型：收费方案、收费期次、收款记录。

对应库表 ``fee_plan`` / ``fee_period`` / ``payment``（表已建好，此处仅做映射）。
三者是「方案 → 期次 → 收款」的层级关系，收款支持一笔期次多次部分收款。
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class FeePlan(Base):
    """收费方案：一个案件可有多份方案（如一审、二审分别立项）。

    ``fee_type``：fixed 固定 / ratio 比例 / risk 风险 / hourly 计时。
    ``total_amount`` 为方案总额，正常情况下应等于其下全部期次 ``due_amount`` 之和。
    """

    __tablename__ = "fee_plan"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="关联案件"
    )
    fee_type: Mapped[str] = mapped_column(
        Enum("fixed", "ratio", "risk", "hourly", name="fee_type"),
        nullable=False,
        default="fixed",
        comment="收费方式：固定/比例/风险/计时",
    )
    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), comment="收费总额"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="收费说明"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    # 非数据库字段：service 层查询后注入，供序列化输出。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    case_no = None
    case_title = None
    client_id = None
    client_name = None
    due_total = None  # 应收合计
    paid_total = None  # 已收合计
    period_count = None  # 期次数量
    pending_order_count = 0  # 进行中的在线支付订单数
    pending_order_amount = Decimal("0.00")  # 进行中的在线支付金额

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<FeePlan id={self.id} case_id={self.case_id} total={self.total_amount}>"


class FeePeriod(Base):
    """收费期次：一份方案拆成多期收款（首期/二期/尾款）。

    ``paid_amount`` 是冗余累计值，用于快速判定 ``status``：
    ``unpaid`` 未收款 / ``partial`` 部分收款 / ``paid`` 已结清。
    """

    __tablename__ = "fee_period"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    fee_plan_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="所属收费方案"
    )
    period_no: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, comment="期次序号：1首期 2二期 3尾款"
    )
    due_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), comment="应收金额"
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0.00"),
        comment="已收金额（冗余，便于判定部分收款）",
    )
    due_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="应收日期"
    )
    status: Mapped[str] = mapped_column(
        Enum("unpaid", "partial", "paid", name="fee_period_status"),
        nullable=False,
        default="unpaid",
        comment="状态：未收/部分/已结清",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    # 非数据库字段：逾期天数（service 注入）
    overdue_days = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<FeePeriod id={self.id} plan={self.fee_plan_id} no={self.period_no}>"


class Payment(Base):
    """收款记录：一笔期次可对应多条收款（部分收款）。

    发票信息（``invoice_no`` / ``invoice_title`` / ``invoice_status``）直接并入
    本表，收款时可直接登记，也可事后通过发票接口补录。
    """

    __tablename__ = "payment"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    fee_period_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="所属期次"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, comment="本次实收金额"
    )
    pay_method: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="银行转账/现金/微信/支付宝"
    )
    receipt_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="收据号"
    )
    invoice_no: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="发票号"
    )
    invoice_title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="开票抬头"
    )
    invoice_status: Mapped[str] = mapped_column(
        Enum("none", "applied", "issued", name="invoice_status"),
        nullable=False,
        default="none",
        comment="未开票/申请中/已开票",
    )
    paid_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        comment="收款时间",
    )
    source: Mapped[str] = mapped_column(
        Enum("offline", "online", name="payment_source"),
        nullable=False,
        default="offline",
        comment="收款来源：线下登记/在线支付",
    )
    order_no: Mapped[str | None] = mapped_column(
        String(40), nullable=True, comment="关联支付订单号"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="登记人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Payment id={self.id} period={self.fee_period_id} amount={self.amount}>"
