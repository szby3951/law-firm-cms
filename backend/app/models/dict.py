"""数据字典 ORM 模型：案由、合同类型、文书类型、来源渠道等下拉选项。"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class DictItem(Base):
    """字典项：同一 ``dict_type`` 下按 ``sort`` 升序展示。

    ``(dict_type, value)`` 有唯一约束，重复添加同一值会在数据库层被拒绝。
    """

    __tablename__ = "dict_item"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    dict_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        comment="分类：case_cause/contract_type/doc_type/source_channel",
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False, comment="显示文本")
    value: Mapped[str] = mapped_column(String(64), nullable=False, comment="存储值")
    sort: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, comment="同分类内排序，越小越前"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="创建时间"
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<DictItem {self.dict_type}:{self.value}>"
