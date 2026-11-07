"""律所私有知识库 ORM 模型（FAQ / 案件摘要 / 内部手册）。

对应库表 ``kb_document``：一行 = 一段可被检索的律所自有知识。

与 ``law_article`` 的区别：
- ``law_article`` 是全所共享的**法条原文**，来源固定、按条切分；
- ``kb_document`` 是**本所沉淀**的经验材料（常见问题、历史案件要点、办案手册），
  由管理员上传，正文是自由段落，切块时按段落/句读处理。

两者写入同一个 Qdrant collection（``law_kb``），靠 payload 里的 ``source``
字段区分（``law`` / ``firm``），检索时可以按来源过滤。
"""

from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.mysql import LONGTEXT
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class KbDocument(Base):
    """律所自有知识片段：标题、分类、正文与向量点ID。"""

    __tablename__ = "kb_document"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="标题")
    category: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="faq",
        server_default="faq",
        comment="faq/case_summary/manual",
    )
    content: Mapped[str] = mapped_column(
        Text().with_variant(LONGTEXT, "mysql"),
        nullable=False,
        comment="知识片段正文",
    )
    vector_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="Qdrant 中的向量点ID（首块）"
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="上传人（管理员）"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<KbDocument id={self.id} category={self.category} {self.title!r}>"
