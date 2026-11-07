"""客户档案表 ORM 模型：客户的基本信息、来源、分级与负责律师。"""

from datetime import datetime

from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.user import BigIntPK


class ClientProfile(Base):
    """客户档案：一条记录对应一位客户（个人或机构）。

    ``user_id`` 关联登录账号（自助注册的客户），可为空——律师代录的
    线索客户还没有账号，此时仅靠 ``name`` 字段承载姓名。
    ``lawyer_id`` 是客户的负责律师（owner），用于行级数据隔离。
    """

    __tablename__ = "client_profile"

    id: Mapped[int] = mapped_column(BigIntPK, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="关联登录账号，可为空（律师代录的线索客户）"
    )
    name: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="客户姓名 / 机构名称"
    )
    client_type: Mapped[str] = mapped_column(
        Enum("personal", "company", name="client_type"),
        nullable=False,
        default="personal",
        comment="个人/机构",
    )
    id_no: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="证件号（加密存储，展示脱敏）"
    )
    gender: Mapped[str | None] = mapped_column(String(8), nullable=True, comment="性别")
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="联系电话"
    )
    address: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="联系地址"
    )
    source_channel: Mapped[str | None] = mapped_column(
        String(32), nullable=True, comment="来源渠道：转介绍/网络/门店"
    )
    level: Mapped[str] = mapped_column(
        Enum("vip", "normal", name="client_level"),
        nullable=False,
        default="normal",
        comment="客户分级",
    )
    status: Mapped[str] = mapped_column(
        Enum("potential", "deal", "lost", name="client_status"),
        nullable=False,
        default="potential",
        comment="客户漏斗状态：潜在/成交/流失",
    )
    lawyer_id: Mapped[int | None] = mapped_column(
        BigIntPK, nullable=True, comment="负责律师（owner）"
    )
    ai_profile: Mapped[dict | None] = mapped_column(
        mysql.JSON, nullable=True, comment="AI 客户画像：类型/诉求/风险点/跟进建议"
    )
    ai_profile_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="画像生成时间"
    )
    remark: Mapped[str | None] = mapped_column(Text, nullable=True, comment="备注")
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

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<ClientProfile id={self.id} name={self.name!r}>"
