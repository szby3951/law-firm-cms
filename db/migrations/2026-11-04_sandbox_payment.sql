-- ===========================================================================
-- 沙箱支付：支付订单表 + 收款来源标记
-- 作用：客户在账单页发起在线支付（沙箱模拟），支付成功后落一条 payment 记录，
--       律师端 / 管理员端 / 客户端共用同一份收款数据，天然三端互通。
-- 幂等：本文件由 scripts/migrate_sandbox_payment.py 执行，脚本内做存在性判断。
-- ===========================================================================

CREATE TABLE IF NOT EXISTS `payment_order` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_no`       VARCHAR(40)     NOT NULL              COMMENT '商户订单号（PAY + 时间 + 随机）',
  `fee_period_id`  BIGINT UNSIGNED NOT NULL              COMMENT '所属收费期次',
  `amount`         DECIMAL(12,2)   NOT NULL              COMMENT '应付金额',
  `channel`        VARCHAR(16)     NOT NULL              COMMENT '支付渠道：wechat/alipay/bank',
  `status`         ENUM('pending','paid','failed','cancelled','expired')
                   NOT NULL DEFAULT 'pending'            COMMENT '待支付/已支付/失败/已取消/已过期',
  `payer_id`       BIGINT UNSIGNED NOT NULL              COMMENT '发起支付的客户用户ID',
  `transaction_no` VARCHAR(64)              DEFAULT NULL COMMENT '沙箱网关交易号',
  `payment_id`     BIGINT UNSIGNED          DEFAULT NULL COMMENT '支付成功生成的收款记录ID',
  `fail_reason`    VARCHAR(255)             DEFAULT NULL COMMENT '失败/过期原因',
  `expired_at`     DATETIME        NOT NULL              COMMENT '订单过期时间（创建后 30 分钟）',
  `paid_at`        DATETIME                 DEFAULT NULL COMMENT '支付成功时间',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_order_no` (`order_no`),
  KEY `ix_order_period` (`fee_period_id`),
  KEY `ix_order_status` (`status`),
  KEY `ix_order_payer` (`payer_id`),
  CONSTRAINT `fk_order_period` FOREIGN KEY (`fee_period_id`) REFERENCES `fee_period` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='支付订单（沙箱）';

-- 收款来源：区分律师线下登记与客户在线支付，律师端流水按此展示
ALTER TABLE `payment`
  ADD COLUMN `source`   ENUM('offline','online') NOT NULL DEFAULT 'offline'
      COMMENT '收款来源：线下登记/在线支付' AFTER `paid_at`,
  ADD COLUMN `order_no` VARCHAR(40) DEFAULT NULL
      COMMENT '关联支付订单号' AFTER `source`,
  ADD KEY `ix_pay_order` (`order_no`);
