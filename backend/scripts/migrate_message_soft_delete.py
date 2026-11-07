"""留言软删除字段迁移（幂等）。

执行：``python scripts/migrate_message_soft_delete.py``

给 ``message`` 增加三个列，支持「撤回（发送人 5 分钟内）」与「管理员删除」：

- ``is_deleted``  是否已软删除（默认 0，历史数据全部视为未删除）
- ``deleted_at``  操作时间
- ``deleted_by``  操作人（等于发送人 → 本人撤回；否则 → 管理员删除）

只加列、不改任何既有数据，因此**可以在旧代码仍在运行时执行**：
新列有默认值，旧版本 ORM 不映射它，读写都不受影响。

重复执行安全：加列前查 ``information_schema``，已存在则跳过。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

# 列名 → (DDL 片段, 说明)
COLUMNS: dict[str, tuple[str, str]] = {
    "is_deleted": (
        "ADD COLUMN `is_deleted` TINYINT NOT NULL DEFAULT 0 "
        "COMMENT '是否已撤回/删除（软删除，正文与附件不再下发）' AFTER `is_read`",
        "是否已撤回/删除",
    ),
    "deleted_at": (
        "ADD COLUMN `deleted_at` DATETIME DEFAULT NULL "
        "COMMENT '撤回/删除时间' AFTER `is_deleted`",
        "撤回/删除时间",
    ),
    "deleted_by": (
        "ADD COLUMN `deleted_by` BIGINT UNSIGNED DEFAULT NULL "
        "COMMENT '操作人：发送人本人=撤回，管理员=后台删除' AFTER `deleted_at`",
        "操作人",
    ),
}


async def _columns(conn, table: str) -> set[str]:
    rows = await conn.execute(
        text(
            "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"
        ),
        {"t": table},
    )
    return {r[0] for r in rows}


async def main() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        cols = await _columns(conn, "message")
        if not cols:
            print("✗ 找不到 message 表，请确认连的是对的库：", settings.database_url)
            raise SystemExit(1)

        for name, (ddl, label) in COLUMNS.items():
            if name in cols:
                print(f"- message.{name}（{label}）已存在，跳过")
                continue
            await conn.execute(text(f"ALTER TABLE `message` {ddl}"))
            print(f"✓ message.{name}（{label}）已添加")

        # 回填：历史数据默认未删除，MySQL 的 DEFAULT 0 已经覆盖，
        # 这里补一条显式 UPDATE，防止有人先手工加列但没给默认值
        await conn.execute(
            text("UPDATE `message` SET `is_deleted` = 0 WHERE `is_deleted` IS NULL")
        )

    await engine.dispose()
    print("迁移完成：留言软删除字段就绪")


if __name__ == "__main__":
    asyncio.run(main())
