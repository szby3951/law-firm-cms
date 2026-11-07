"""沙箱支付相关表结构迁移（幂等）。

执行：``python scripts/migrate_sandbox_payment.py``

做两件事：
1. 新建 ``payment_order``（沙箱支付订单）；
2. 给 ``payment`` 增加 ``source`` / ``order_no`` 列与索引。

重复执行安全：建表用 ``IF NOT EXISTS``，加列前查 ``information_schema``。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import settings

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS `payment_order` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_no`       VARCHAR(40)     NOT NULL,
  `fee_period_id`  BIGINT UNSIGNED NOT NULL,
  `amount`         DECIMAL(12,2)   NOT NULL,
  `channel`        VARCHAR(16)     NOT NULL,
  `status`         ENUM('pending','paid','failed','cancelled','expired')
                   NOT NULL DEFAULT 'pending',
  `payer_id`       BIGINT UNSIGNED NOT NULL,
  `transaction_no` VARCHAR(64)              DEFAULT NULL,
  `payment_id`     BIGINT UNSIGNED          DEFAULT NULL,
  `fail_reason`    VARCHAR(255)             DEFAULT NULL,
  `expired_at`     DATETIME        NOT NULL,
  `paid_at`        DATETIME                 DEFAULT NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP
                                   ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `ix_order_period` (`fee_period_id`),
  KEY `ix_order_status` (`status`),
  KEY `ix_order_payer` (`payer_id`),
  CONSTRAINT `fk_order_period` FOREIGN KEY (`fee_period_id`)
      REFERENCES `fee_period` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci
  COMMENT='支付订单（沙箱）'
"""


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
        await conn.execute(text(CREATE_TABLE))
        print("✓ payment_order 表就绪")

        cols = await _columns(conn, "payment")
        if "source" not in cols:
            await conn.execute(
                text(
                    "ALTER TABLE `payment` ADD COLUMN `source` "
                    "ENUM('offline','online') NOT NULL DEFAULT 'offline' "
                    "COMMENT '收款来源：线下登记/在线支付' AFTER `paid_at`"
                )
            )
            print("✓ payment.source 已添加")
        else:
            print("- payment.source 已存在，跳过")

        if "order_no" not in cols:
            await conn.execute(
                text(
                    "ALTER TABLE `payment` ADD COLUMN `order_no` VARCHAR(40) "
                    "DEFAULT NULL COMMENT '关联支付订单号' AFTER `source`"
                )
            )
            print("✓ payment.order_no 已添加")
        else:
            print("- payment.order_no 已存在，跳过")

        idx = await conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.STATISTICS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'payment' "
                "AND INDEX_NAME = 'ix_pay_order'"
            )
        )
        if not idx.scalar_one():
            await conn.execute(
                text("ALTER TABLE `payment` ADD KEY `ix_pay_order` (`order_no`)")
            )
            print("✓ payment.ix_pay_order 已添加")
        else:
            print("- payment.ix_pay_order 已存在，跳过")

    await engine.dispose()
    print("迁移完成")


if __name__ == "__main__":
    asyncio.run(main())
