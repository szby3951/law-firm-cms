"""通用附件表 ORM 模型：证据/材料/合同文件等统一存储元信息。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class Attachment(Base):
    """通用附件：记录文件元信息，实际文件落盘在 upload 目录。

    ``biz_type`` 区分业务类型（case/contract/message/document），
    ``biz_id`` 为对应业务主键。
    """

    __tablename__ = "attachment"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    biz_type: Mapped[str] = mapped_column(
        String(32), nullable=False, comment="case/contract/message/document"
    )
    biz_id: Mapped[int] = mapped_column(BigIntPK, nullable=False, comment="业务主键")
    file_name: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="原始文件名"
    )
    file_path: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="相对存储路径"
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, comment="文件大小（字节）"
    )
    mime_type: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="MIME 类型"
    )
    uploader_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="上传人"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="上传时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<Attachment id={self.id} biz={self.biz_type}:{self.biz_id}>"
