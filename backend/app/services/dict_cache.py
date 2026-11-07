"""数据字典的运行期缓存。

字典是可配置的下拉候选，但**显示标签**散落在文书、合同等模块里。为了让
「管理员改字典 → 页面标签同步」成立，启动时把 dict_item 全量读进内存，
写操作后再刷新；显示时走同步的 :func:`label_of`，无需在每个请求里查库。

缓存只存 ``{dict_type: {value: label}}``，体量很小（当前 23 条），
全量重载的成本可以忽略。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.dict import DictItem

_CACHE: dict[str, dict[str, str]] = {}


async def refresh(db: AsyncSession) -> int:
    """全量重载字典缓存，返回条目数。写操作后由调用方触发。"""
    rows = (
        (
            await db.execute(
                select(DictItem).order_by(
                    DictItem.dict_type.asc(), DictItem.sort.asc(), DictItem.id.asc()
                )
            )
        )
        .scalars()
        .all()
    )
    cache: dict[str, dict[str, str]] = {}
    for row in rows:
        cache.setdefault(row.dict_type, {})[row.value] = row.label

    _CACHE.clear()
    _CACHE.update(cache)
    return len(rows)


def label_of(dict_type: str, value: str | None, fallback: str | None = None) -> str:
    """取显示标签；字典里没有该取值时用 fallback（再退回原值）。"""
    if not value:
        return fallback or ""
    return _CACHE.get(dict_type, {}).get(value, fallback or value)


def options(dict_type: str) -> list[dict[str, str]]:
    """某分类下的候选列表，顺序与后台排序一致。"""
    return [
        {"label": label, "value": value}
        for value, label in _CACHE.get(dict_type, {}).items()
    ]


def snapshot() -> dict[str, list[dict[str, str]]]:
    """全部候选，按分类分组（供前端一次性拉取）。"""
    return {dict_type: options(dict_type) for dict_type in _CACHE}


def loaded() -> bool:
    """缓存是否已加载（测试与排障用）。"""
    return bool(_CACHE)
