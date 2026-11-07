"""用户表 ORM 模型：三种角色（客户/律师/管理员）共用一张表。"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Enum, String, func
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base

# 与建表脚本一致使用 BIGINT UNSIGNED，避免外键类型不匹配
BigIntPK = BigInteger().with_variant(mysql.BIGINT(unsigned=True), "mysql")


class User(Base):
    """用户表。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(
        BigIntPK, primary_key=True, autoincrement=True, comment="用户ID"
    )
    username: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        nullable=False,
        comment="登录账号：客户用手机号，律师/管理员用工号",
    )
    password_hash: Mapped[str] = mapped_column(
        String(255), nullable=False, comment="bcrypt 哈希"
    )
    real_name: Mapped[str] = mapped_column(
        String(64), nullable=False, default="", comment="真实姓名"
    )
    role: Mapped[str] = mapped_column(
        Enum("client", "lawyer", "admin", name="user_role"),
        nullable=False,
        default="client",
        comment="角色",
    )
    phone: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="手机号"
    )
    email: Mapped[str | None] = mapped_column(
        String(128), nullable=True, comment="邮箱"
    )
    avatar: Mapped[str | None] = mapped_column(
        String(255), nullable=True, comment="头像URL"
    )
    status: Mapped[int] = mapped_column(
        mysql.TINYINT, nullable=False, default=1, comment="1=正常 0=禁用"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), comment="注册时间"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"<User id={self.id} username={self.username!r} role={self.role!r}>"
