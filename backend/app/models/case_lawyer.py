"""案件-律师关联表 ORM 模型：多对多，记录主办/协办关系。"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class CaseLawyer(Base):
    """案件与律师的承办关系（多对多）。

    联合主键 ``(case_id, lawyer_id)``；``duty`` 区分主办（lead）/协办（assist）。
    一个案件可有多个律师，一个律师可承办多个案件。
    """

    __tablename__ = "case_lawyer"

    case_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, nullable=False, comment="案件"
    )
    lawyer_id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, nullable=False, comment="律师"
    )
    duty: Mapped[str] = mapped_column(
        Enum("lead", "assist", name="case_lawyer_duty"),
        nullable=False,
        default="lead",
        comment="主办/协办",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="分配时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<CaseLawyer case_id={self.case_id} lawyer_id={self.lawyer_id} duty={self.duty}>"
