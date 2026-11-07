"""案件表 ORM 模型：案件基本信息与全生命周期状态。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Case(Base):
    """案件：一条记录对应一个委托案件。

    ``client_id`` 关联委托客户；``created_by`` 记录立案人。
    案件与律师的承办关系存放在 ``CaseLawyer`` 多对多表中。
    """

    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_no: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, comment="案号 / 内部编号"
    )
    client_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, comment="委托客户")
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="案件标题")
    case_cause: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="案由"
    )
    case_type: Mapped[str] = mapped_column(
        Enum("litigation", "non_litigation", name="case_type"),
        nullable=False,
        default="litigation",
        comment="诉讼/非诉",
    )
    court: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="受理法院/机构"
    )
    opposing_party: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="对方当事人"
    )
    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0.00"), comment="标的额"
    )
    status: Mapped[str] = mapped_column(
        Enum(
            "consulting",
            "filed",
            "handling",
            "pending_close",
            "closed",
            "withdrawn",
            name="case_status",
        ),
        nullable=False,
        default="consulting",
        comment="案件状态",
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="案情描述"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="立案人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="结案时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 非数据库字段：主办律师姓名（service 层列表查询后批量注入，供序列化输出）。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    lead_lawyer_name = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Case id={self.id} case_no={self.case_no!r}>"
