"""系统设置业务逻辑：数据字典、律所信息、AI 配置。

AI 配置是唯一「会改变进程运行期行为」的设置：``status=1`` 时用它覆盖
``.env`` 里的对话模型参数，关闭时回滚到启动时的 .env 快照。
"""

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import BadRequest, Conflict, NotFound
from app.models.dict import DictItem
from app.models.setting import AIConfig, FirmInfo
from app.schemas.setting import (
    AIConfigIn,
    AIConfigOut,
    DictItemIn,
    DictItemOut,
    DictTypeOut,
    FirmInfoIn,
)
from app.services import dict_cache

# 运行期可被数据库配置覆盖的对话模型参数
_AI_FIELDS = ("llm_provider", "llm_base_url", "llm_model", "llm_temperature", "llm_api_key")

# .env 原始值快照：关闭 AI 配置时用它回滚，避免「关不掉」
_ENV_SNAPSHOT: dict[str, object] = {}


def _snapshot_env() -> None:
    """首次应用前记下 .env 的值（进程内只记一次）。"""
    if _ENV_SNAPSHOT:
        return
    for field in _AI_FIELDS:
        _ENV_SNAPSHOT[field] = getattr(settings, field)


def mask_api_key(key: str | None) -> str:
    """API Key 脱敏：保留前 4 位与后 4 位，中间打码。"""
    if not key:
        return ""
    text = key.strip()
    if len(text) <= 8:
        return "*" * len(text)
    return f"{text[:4]}{'*' * 6}{text[-4:]}"


# ---------------------------------------------------------------- 数据字典


async def list_dicts(
    db: AsyncSession, dict_type: str | None = None
) -> tuple[list[DictItemOut], list[DictTypeOut]]:
    """按分类查询字典项，同时返回全部分类及条目数。"""
    stmt = select(DictItem).order_by(DictItem.dict_type.asc(), DictItem.sort.asc(), DictItem.id.asc())
    if dict_type:
        stmt = stmt.where(DictItem.dict_type == dict_type)
    rows = (await db.execute(stmt)).scalars().all()

    stats = (
        await db.execute(
            select(DictItem.dict_type, func.count())
            .group_by(DictItem.dict_type)
            .order_by(DictItem.dict_type.asc())
        )
    ).all()

    return (
        [DictItemOut.model_validate(r) for r in rows],
        [DictTypeOut(dict_type=t, count=int(c)) for t, c in stats],
    )


async def _assert_dict_unique(
    db: AsyncSession, dict_type: str, value: str, exclude_id: int | None = None
) -> None:
    """同一分类下的存储值必须唯一（与数据库唯一索引保持一致的口径）。"""
    stmt = select(DictItem.id).where(
        DictItem.dict_type == dict_type, DictItem.value == value
    )
    if exclude_id is not None:
        stmt = stmt.where(DictItem.id != exclude_id)
    if await db.scalar(stmt):
        raise Conflict(f"分类 {dict_type} 下已存在取值 {value}")


async def create_dict(db: AsyncSession, payload: DictItemIn) -> DictItem:
    """新增字典项。"""
    await _assert_dict_unique(db, payload.dict_type, payload.value)
    item = DictItem(**payload.model_dump())
    db.add(item)
    await db.commit()
    await db.refresh(item)
    # 表单下拉与显示标签都读缓存，写完立刻刷新
    await dict_cache.refresh(db)
    return item


async def update_dict(db: AsyncSession, item_id: int, payload: DictItemIn) -> DictItem:
    """修改字典项（分类与取值都可改，改后仍需唯一）。"""
    item = await db.get(DictItem, item_id)
    if item is None:
        raise NotFound("字典项不存在")
    await _assert_dict_unique(db, payload.dict_type, payload.value, exclude_id=item_id)

    for field, value in payload.model_dump().items():
        setattr(item, field, value)
    await db.commit()
    await db.refresh(item)
    await dict_cache.refresh(db)
    return item


async def delete_dict(db: AsyncSession, item_id: int) -> None:
    """删除字典项。

    历史数据里可能仍在用这个取值，这里只做提示不做阻断——字典是下拉候选，
    删掉不影响已有记录展示。
    """
    item = await db.get(DictItem, item_id)
    if item is None:
        raise NotFound("字典项不存在")
    await db.delete(item)
    await db.commit()
    await dict_cache.refresh(db)


# ---------------------------------------------------------------- 律所信息


async def get_firm(db: AsyncSession) -> FirmInfo:
    """读取律所信息，缺失时补一条默认记录（兼容旧库）。"""
    firm = await db.scalar(select(FirmInfo).order_by(FirmInfo.id.asc()))
    if firm is None:
        firm = FirmInfo(
            name=settings.firm_name,
            address=None,
            phone=None,
            intro=None,
        )
        db.add(firm)
        await db.commit()
        await db.refresh(firm)
    return firm


async def update_firm(db: AsyncSession, payload: FirmInfoIn) -> FirmInfo:
    """更新律所信息；同时刷新 RAG 提示词里用的律所名。"""
    firm = await get_firm(db)
    for field, value in payload.model_dump().items():
        setattr(firm, field, value)
    await db.commit()
    await db.refresh(firm)

    # AI 提示词里写的是「你是XX律所的法律顾问」，改完立即生效
    settings.firm_name = firm.name
    return firm


# ---------------------------------------------------------------- AI 配置


async def _get_ai_row(db: AsyncSession) -> AIConfig | None:
    return await db.scalar(select(AIConfig).order_by(AIConfig.id.asc()))


def apply_ai_config(row: AIConfig | None) -> str:
    """把数据库配置应用到运行期 settings，返回生效来源（``db`` / ``env``）。

    只有「启用 + 有 Key」才覆盖；否则回滚到 .env 快照。
    """
    _snapshot_env()

    enabled = row is not None and row.status == 1 and bool((row.api_key or "").strip())
    if not enabled:
        for field, value in _ENV_SNAPSHOT.items():
            setattr(settings, field, value)
        return "env"

    settings.llm_provider = row.provider
    settings.llm_base_url = row.base_url
    settings.llm_model = row.model
    settings.llm_temperature = float(row.temperature)
    settings.llm_api_key = row.api_key.strip()
    return "db"


def active_source(row: AIConfig | None) -> str:
    """生效来源：启用且有 Key 时走数据库，否则走 .env。"""
    if row is not None and row.status == 1 and bool((row.api_key or "").strip()):
        return "db"
    return "env"


async def load_ai_config(db: AsyncSession) -> str:
    """启动时调用：读库并应用，返回生效来源。"""
    row = await _get_ai_row(db)
    return apply_ai_config(row)


def _to_out(row: AIConfig) -> AIConfigOut:
    """ORM → 输出模型（Key 脱敏 + 生效来源）。"""
    _snapshot_env()
    return AIConfigOut(
        provider=row.provider,
        base_url=row.base_url,
        model=row.model,
        temperature=float(row.temperature),
        embedding_model=row.embedding_model,
        status=row.status,
        updated_at=row.updated_at,
        api_key_masked=mask_api_key(row.api_key),
        api_key_set=bool((row.api_key or "").strip()),
        env_model=str(_ENV_SNAPSHOT.get("llm_model") or settings.llm_model),
        active_model=settings.llm_model,
        active_source=active_source(row),
    )


async def get_ai_config(db: AsyncSession) -> AIConfigOut:
    """读取 AI 配置（Key 脱敏）。"""
    row = await _get_ai_row(db)
    if row is None:
        raise NotFound("AI 配置尚未初始化")
    return _to_out(row)


async def update_ai_config(db: AsyncSession, payload: AIConfigIn) -> AIConfigOut:
    """保存 AI 配置并立即生效（或回滚到 .env）。"""
    row = await _get_ai_row(db)
    if row is None:
        row = AIConfig()
        db.add(row)

    row.provider = payload.provider
    row.base_url = payload.base_url
    row.model = payload.model
    row.temperature = payload.temperature
    row.embedding_model = payload.embedding_model
    row.status = payload.status
    # 留空表示不改：前端不回显明文，避免把脱敏串写回库里
    if payload.api_key:
        row.api_key = payload.api_key.strip()

    if row.status == 1 and not (row.api_key or "").strip():
        raise BadRequest("启用数据库配置前请先填写 API Key")

    try:
        await db.commit()
    except IntegrityError as exc:  # pragma: no cover - 单行表，理论不会触发
        await db.rollback()
        raise Conflict("AI 配置保存失败，请重试") from exc
    await db.refresh(row)

    apply_ai_config(row)
    return _to_out(row)

