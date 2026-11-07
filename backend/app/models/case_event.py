"""案件节点时间线表 ORM 模型：立案/受理/开庭等节点留痕。"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class CaseEvent(Base):
    """案件节点：记录案件进展的关键时间节点，构成时间线。"""

    __tablename__ = "case_event"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, comment="案件")
    event_type: Mapped[str] = mapped_column(
        Enum(
            "filing",
            "accept",
            "hearing",
            "evidence",
            "judgment",
            "other",
            name="case_event_type",
        ),
        nullable=False,
        default="other",
        comment="节点类型",
    )
    event_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="节点时间"
    )
    description: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="说明"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="登记人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="登记时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<CaseEvent id={self.id} case_id={self.case_id} type={self.event_type}>"
