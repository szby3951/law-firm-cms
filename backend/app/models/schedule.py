"""日程 ORM 模型：开庭、期限、回访、会议等日程安排。

对应库表 ``schedule``（表已建好，此处仅做映射）。
``user_id`` 是日程归属的承办律师，行级隔离以此为准；``case_id`` / ``client_id``
可选，用于把日程挂到具体案件或客户上。
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Schedule(Base):
    """日程：一条记录对应一次开庭/期限/回访/会议。

    ``remind_at`` 为提醒时间，定时任务据此生成站内通知；为空时退化为
    「事件前 N 天」提醒（见 ``app/scheduler.py``）。
    """

    __tablename__ = "schedule"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联案件，可为空"
    )
    client_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联客户，可为空"
    )
    user_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="承办律师（日程归属人）"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="日程标题")
    schedule_type: Mapped[str] = mapped_column(
        Enum("hearing", "deadline", "visit", "meeting", name="schedule_type"),
        nullable=False,
        default="hearing",
        comment="类型：开庭/期限/回访/会议",
    )
    event_date: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, comment="日程时间"
    )
    remind_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="提醒时间"
    )
    status: Mapped[str] = mapped_column(
        Enum("pending", "done", "cancelled", name="schedule_status"),
        nullable=False,
        default="pending",
        comment="状态：待办/已完成/已取消",
    )
    remark: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="备注"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    # 非数据库字段：service 层查询后注入，供序列化输出。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    case_no = None
    case_title = None
    client_name = None
    lawyer_name = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<Schedule id={self.id} type={self.schedule_type} "
            f"event={self.event_date}>"
        )
