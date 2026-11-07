"""站内通知 ORM 模型。

对应库表 ``notification``：一条记录 = 某个用户的一条通知。
``type`` 用于区分来源（开庭/期限/缴费/跟进/合同/系统），
``related_type`` + ``related_id`` 指向业务对象，便于前端点击跳转。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Notification(Base):
    """站内通知：接收人、标题内容、已读标记与来源关联。"""

    __tablename__ = "notification"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="接收人"
    )
    title: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="通知标题"
    )
    content: Mapped[str | None] = mapped_column(
        String(1000), nullable=True, comment="通知内容"
    )
    type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="system",
        server_default="system",
        comment="hearing/deadline/payment/follow/contract/system",
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否已读",
    )
    related_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="关联对象类型：case/schedule/contract"
    )
    related_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联对象ID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Notification id={self.id} user={self.user_id} type={self.type}>"
