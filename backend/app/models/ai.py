"""AI 会话与消息 ORM 模型（任务拆解 9.3.4）。

两件事分开存：

- ``ai_session``：一次对话的「壳」。``type`` 预留了 document/contract/case/profile，
  9.4~9.7 复用同一张表，用 ``related_id`` 指向案件/合同/客户，避免每加一个功能
  就新建一张会话表。
- ``ai_message``：每轮问答一条。``refs`` 存本次回答引用的法条/知识原文快照，
  **不能只存 article_id**——知识库会随法规修订而变，快照才能让历史回答可复现、
  可审计（9.9.3）。

``ai_message.session_id`` 上有 ``ON DELETE CASCADE``，删除会话时消息由数据库
一并清理，因此模型里不建 relationship，避免异步上下文里隐式懒加载报
``MissingGreenlet``。
"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK

# 会话类型：9.3 chat / 9.4 document / 9.5 contract / 9.6 case；profile 留给 9.7
AI_SESSION_TYPES = (
    "chat",  # AI 法律问答（检索法条）
    "business",  # AI督办（读业务台账，不检索）
    "document",
    "contract",
    "case",
    "profile",
)


class AiSession(Base):
    """AI 会话：一条用户与助手的连续对话。"""

    __tablename__ = "ai_session"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        BigIntPK, nullable=False, comment="所属用户"
    )
    type: Mapped[str] = mapped_column(
        Enum(*AI_SESSION_TYPES, name="ai_session_type"),
        nullable=False,
        default="chat",
        server_default="chat",
        comment="会话类型",
    )
    related_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联案件/合同/客户ID"
    )
    title: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="会话标题（默认取首个问题）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="最后活跃时间",
    )

    __table_args__ = (Index("ix_ais_user", "user_id", "created_at"),)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<AiSession id={self.id} user={self.user_id} {self.title!r}>"


class AiMessage(Base):
    """AI 消息：用户提问或助手回答。"""

    __tablename__ = "ai_message"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        BigIntPK,
        ForeignKey("ai_session.id", ondelete="CASCADE", name="fk_aim_session"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(
        Enum("system", "user", "assistant", name="ai_message_role"),
        nullable=False,
        comment="角色",
    )
    content: Mapped[str] = mapped_column(
        Text().with_variant(mysql.LONGTEXT, "mysql"),
        nullable=False,
        comment="消息正文",
    )
    refs: Mapped[list | None] = mapped_column(
        mysql.JSON,
        nullable=True,
        comment="法条引用快照：[{index,law_name,article_no,content,score,...}]",
    )
    token_usage: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="token 用量（估算）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    __table_args__ = (Index("ix_aim_session", "session_id", "id"),)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<AiMessage id={self.id} session={self.session_id} {self.role}>"
