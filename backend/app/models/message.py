"""沟通留言 ORM 模型。

对应库表 ``message``（表已建好，此处仅做映射）。

设计要点：

- 会话由 ``(client_id, lawyer_id)`` 唯一确定，``lawyer_id`` 记录**会话的律师
  一方**，而不是「本条消息的接收人」。这样无论谁发消息，都能用同一维度
  聚合出会话列表，不必按发送方向切换过滤条件。
- ``sender_id`` / ``sender_role`` 记录本条消息的实际发送人。
- ``is_read`` 表示**对方**是否已读：客户发的消息由律师读后置 1，律师发的
  消息由客户读后置 1；发送人自己的已读状态没有意义。
- 附件不入 ``message`` 表，统一存 ``attachment``（``biz_type='message'``，
  ``biz_id=message.id``），与案件材料、合同文件共用一套存储与下载逻辑。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Message(Base):
    """一条沟通留言（会话中的一句话）。"""

    __tablename__ = "message"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联案件，可为空（纯咨询性沟通）"
    )
    client_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="会话客户（client_profile.id）"
    )
    lawyer_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="会话律师（user.id），即会话对方"
    )
    sender_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="发送人（user.id）"
    )
    sender_role: Mapped[str] = mapped_column(
        Enum("client", "lawyer", name="message_sender_role"),
        nullable=False,
        comment="发送人角色：client 客户 / lawyer 律师",
    )
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="正文（可只有附件）"
    )
    is_read: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="对方是否已读",
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="发送时间"
    )

    # 非数据库字段：service 层聚合后注入，供序列化直接输出。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    client_name = None
    lawyer_name = None
    sender_name = None
    case_no = None
    attachments = None
    is_mine = False

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return (
            f"<Message id={self.id} client={self.client_id} "
            f"lawyer={self.lawyer_id} from={self.sender_role}>"
        )
