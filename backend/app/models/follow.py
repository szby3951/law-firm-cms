"""跟进记录表 ORM 模型：律师对客户的每一次跟进留痕。"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class FollowRecord(Base):
    """跟进记录：记录跟进方式、内容与下次跟进日期。"""

    __tablename__ = "follow_record"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    client_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, comment="客户")
    user_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="跟进人（律师）"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="跟进内容")
    method: Mapped[str] = mapped_column(
        Enum("phone", "wechat", "visit", "email", name="follow_method"),
        nullable=False,
        default="phone",
        comment="跟进方式",
    )
    next_follow_date: Mapped[date | None] = mapped_column(
        Date, nullable=True, comment="下次跟进日期"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="跟进时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<FollowRecord id={self.id} client_id={self.client_id}>"
