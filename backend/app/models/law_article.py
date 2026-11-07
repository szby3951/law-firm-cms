"""法律条文 ORM 模型（RAG 知识库的结构化底座）。

对应库表 ``law_article``：一行 = 一条法律条文（按「条」切分）。

设计要点：
- ``law_name`` + ``article_no`` 唯一，重复导入靠它去重（幂等）；
- ``content`` 存**完整原文**，不在入库阶段截断，切块只发生在向量化阶段；
- ``vector_id`` 记录该条文在 Qdrant 中的**首个**向量点 ID。超长条文会被切成
  多个点，payload 中带 ``chunk_index`` / ``chunk_count`` 与 ``article_id``，
  检索命中的是哪一个分块可以直接回查本表拿到完整原文。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class LawArticle(Base):
    """法律条文：法律名、章节、条号与原文。"""

    __tablename__ = "law_article"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    law_name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="法律名称：民法典/刑法..."
    )
    chapter: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="章节（编/章）"
    )
    article_no: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="条号，如「第五百八十五条」"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="条文原文")
    effective_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="有效",
        server_default="有效",
        comment="效力状态：有效/已修订/已废止",
    )
    vector_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Qdrant 中的向量点ID（首块）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<LawArticle {self.law_name}{self.article_no}>"
