"""合同台账 ORM 模型：合同基本信息、金额、起止日期、状态与 AI 审查结果。"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Enum, Numeric, String, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Contract(Base):
    """合同：一条记录对应一份委托合同。

    ``case_id`` 可空（合同可先于案件签约）；``client_id`` 必填关联委托客户。
    ``ai_review_report`` 存储 AI 风险审查的结构化结果（JSON）。
    """

    __tablename__ = "contract"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联案件，可为空"
    )
    client_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, comment="委托客户")
    name: Mapped[str] = mapped_column(String(255), nullable=False, comment="合同名称")
    contract_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="委托代理/风险代理/其他"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), comment="合同金额"
    )
    start_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="生效日期"
    )
    end_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="到期日期"
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "active", "expired", "terminated", name="contract_status"),
        nullable=False,
        default="draft",
        comment="状态：草稿/生效/到期/终止",
    )
    file_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="合同文件路径"
    )
    ai_review_report: Mapped[dict | None] = mapped_column(
        mysql.JSON, nullable=True, comment="AI 审查结果"
    )
    ai_review_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="AI 审查时间"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="登记人"
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

    # 非数据库字段：关联客户姓名（service 层查询后注入，供序列化输出）。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    client_name = None
    # 非数据库字段：关联案件标题（service 层查询后注入）。
    case_title = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Contract id={self.id} name={self.name!r}>"
