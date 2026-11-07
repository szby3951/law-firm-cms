"""数据库连接层：异步 engine + session 工厂 + ORM 基类。"""

from collections.abc import AsyncGenerator

from sqlalchemy import MetaData
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

# 统一约束命名，避免 MySQL 自动生成随机名，方便后续写迁移
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


engine = create_async_engine(
    settings.database_url,
    echo=settings.db_echo,
    pool_pre_ping=True,  # 取连接前探活，避免 MySQL 空闲断连报错
    pool_recycle=3600,
    pool_size=settings.db_pool_size,
    max_overflow=settings.db_max_overflow,
)

SessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # 提交后仍可读取对象属性，响应序列化不会触发额外查询
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession]:
    """FastAPI 依赖：每个请求一个会话。

    请求正常结束自动提交，抛异常自动回滚。
    需要在事务中间提交/回滚的场景，服务层可自行 ``await session.commit()``。
    """
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def create_all() -> None:
    """按模型定义建表。

    仅用于开发初期快速起步；表结构稳定后应改为版本化迁移脚本，
    且不要在应用启动时执行（生产环境会误建/漏改表）。
    """
    from app import models  # noqa: F401  导入以触发模型注册到 Base.metadata

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def dispose_engine() -> None:
    """应用关闭时释放连接池。"""
    await engine.dispose()
