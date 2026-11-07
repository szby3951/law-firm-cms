"""文书 ORM 模型：文书模板与案件文书库。

对应库表 ``doc_template`` / ``document``（表已建好，此处仅做映射）。

模板正文用 ``{变量}`` 占位，生成草稿时由服务层从案件/客户档案取值替换；
文书正文存富文本 HTML，导出 docx 时按块解析排版。
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class DocTemplate(Base):
    """文书模板：可复用的起诉状/律师函/代理词等骨架。"""

    __tablename__ = "doc_template"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    doc_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="文书类型：complaint/lawyer_letter..."
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False, comment="模板名称")
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="含 {变量} 占位符的正文"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 非数据库字段：service 层解析后注入，供列表序列化输出。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    var_keys = None
    excerpt = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DocTemplate id={self.id} type={self.doc_type} name={self.name!r}>"


class Document(Base):
    """案件文书：一篇文章对应一份文书草稿/定稿。

    ``case_id`` 可空（可先写通用文书再归档）；``client_id`` 为冗余字段，
    便于客户端直接按客户过滤。``status='published'`` 表示对客户可见。
    """

    __tablename__ = "document"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    case_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联案件，可为空"
    )
    client_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="冗余客户ID，便于客户端查询"
    )
    doc_type: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="文书类型"
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="文书标题")
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="富文本正文（HTML）"
    )
    is_ai_generated: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
        comment="是否 AI 生成",
    )
    ai_session_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="AI 会话ID（模块8）"
    )
    file_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="导出的 docx 相对路径"
    )
    status: Mapped[str] = mapped_column(
        Enum("draft", "final", "published", name="document_status"),
        nullable=False,
        default="draft",
        comment="draft 草稿 / final 定稿 / published 客户可见",
    )
    created_by: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="创建人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    # 非数据库字段：service 层查询后注入，供序列化输出。
    # 注意：不能写类型注解，否则 SQLAlchemy 会当作映射列解析而报错。
    case_no = None
    case_title = None
    client_name = None
    creator_name = None
    excerpt = None

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Document id={self.id} title={self.title!r}>"
