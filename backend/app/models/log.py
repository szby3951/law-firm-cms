"""操作审计日志 ORM 模型。"""

from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class OperationLog(Base):
    """操作日志：登录、删除、导出等敏感操作留痕。"""

    __tablename__ = "operation_log"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="操作人"
    )
    action: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        comment="动作：login/logout/register/create/update/delete/export",
    )
    target: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="操作对象：表名或业务标识"
    )
    detail: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="补充说明"
    )
    ip: Mapped[str | None] = mapped_column(String(64), nullable=True, comment="来源IP")
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="操作时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<OperationLog action={self.action!r} target={self.target!r}>"
