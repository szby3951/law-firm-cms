"""系统设置 ORM 模型：律所信息与 AI 配置（均为单行表）。"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class FirmInfo(Base):
    """律所信息：全所共用一份，用于登录页、文书抬头与 AI 提示词。"""

    __tablename__ = "firm_info"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(128), nullable=False, default="示例律师事务所", comment="律所名称"
    )
    logo: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="Logo 地址")
    address: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="地址")
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="联系电话")
    intro: Mapped[str | None] = mapped_column(Text, nullable=True, comment="简介")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class AIConfig(Base):
    """AI 配置：``status=1`` 时覆盖 .env 中的对话模型配置。

    只覆盖对话链路（provider/base_url/api_key/model/temperature）；
    ``embedding_model`` 仅作记录——向量库维度与向量化服务绑定，
    运行期改它会让既有向量失效，必须走重建流程。
    """

    __tablename__ = "ai_config"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(
        String(32), nullable=False, default="deepseek", comment="供应商标识"
    )
    base_url: Mapped[str] = mapped_column(String(255), nullable=False, comment="接口地址")
    api_key: Mapped[str | None] = mapped_column(String(255), nullable=True, comment="API Key")
    model: Mapped[str] = mapped_column(String(64), nullable=False, comment="对话模型")
    temperature: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("0.30"), comment="采样温度"
    )
    embedding_model: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="嵌入模型（仅记录）"
    )
    status: Mapped[int] = mapped_column(
        nullable=False, default=0, comment="1=启用（优先于 .env）"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )
