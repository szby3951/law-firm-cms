-- ============================================================================
-- 基于 LLM 的律所客户智能管理系统 —— 数据库建表脚本
-- 目标环境：MySQL 8.0+ / InnoDB / utf8mb4
-- 用法：
--   1) Navicat 新建连接 → 右键「运行 SQL 文件」选中本文件
--   2) 或命令行：mysql -u root -p < schema.sql
-- 注意：脚本开头会 DROP 同名表，重复执行会清空数据，请勿在已有数据上误跑
-- ============================================================================

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

CREATE DATABASE IF NOT EXISTS `law_firm`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;

USE `law_firm`;

-- ---------------------------------------------------------------------------
-- 0. 清理（按依赖倒序）
-- ---------------------------------------------------------------------------
DROP TABLE IF EXISTS `operation_log`;
DROP TABLE IF EXISTS `ai_message`;
DROP TABLE IF EXISTS `ai_session`;
DROP TABLE IF EXISTS `notification`;
DROP TABLE IF EXISTS `message`;
DROP TABLE IF EXISTS `attachment`;
DROP TABLE IF EXISTS `schedule`;
DROP TABLE IF EXISTS `document`;
DROP TABLE IF EXISTS `doc_template`;
DROP TABLE IF EXISTS `payment`;
DROP TABLE IF EXISTS `fee_period`;
DROP TABLE IF EXISTS `fee_plan`;
DROP TABLE IF EXISTS `contract`;
DROP TABLE IF EXISTS `case_event`;
DROP TABLE IF EXISTS `case_lawyer`;
DROP TABLE IF EXISTS `cases`;
DROP TABLE IF EXISTS `follow_record`;
DROP TABLE IF EXISTS `client_profile`;
DROP TABLE IF EXISTS `kb_document`;
DROP TABLE IF EXISTS `law_article`;
DROP TABLE IF EXISTS `dict_item`;
DROP TABLE IF EXISTS `firm_info`;
DROP TABLE IF EXISTS `ai_config`;
DROP TABLE IF EXISTS `user`;


-- ===========================================================================
-- 一、用户与权限
-- ===========================================================================

CREATE TABLE `user` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '用户ID',
  `username`      VARCHAR(64)     NOT NULL                COMMENT '登录账号：客户用手机号，律师/管理员用工号',
  `password_hash` VARCHAR(255)    NOT NULL                COMMENT 'bcrypt 哈希',
  `real_name`     VARCHAR(64)     NOT NULL DEFAULT ''     COMMENT '真实姓名',
  `role`          ENUM('client','lawyer','admin') NOT NULL DEFAULT 'client' COMMENT '角色',
  `phone`         VARCHAR(20)              DEFAULT NULL   COMMENT '手机号',
  `email`         VARCHAR(128)             DEFAULT NULL   COMMENT '邮箱',
  `avatar`        VARCHAR(255)             DEFAULT NULL   COMMENT '头像URL',
  `status`        TINYINT         NOT NULL DEFAULT 1      COMMENT '1=正常 0=禁用',
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_username` (`username`),
  KEY `ix_user_role`  (`role`),
  KEY `ix_user_phone` (`phone`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户表（三角色共用）';

CREATE TABLE `operation_log` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED          DEFAULT NULL COMMENT '操作人',
  `action`     VARCHAR(64)     NOT NULL              COMMENT '动作：login/logout/create/update/delete/export/ai_chat',
  `target`     VARCHAR(128)             DEFAULT NULL COMMENT '操作对象：表名或业务标识',
  `detail`     VARCHAR(500)             DEFAULT NULL COMMENT '补充说明',
  `ip`         VARCHAR(64)              DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_log_user` (`user_id`),
  KEY `ix_log_time` (`created_at`),
  KEY `ix_log_action` (`action`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='操作审计日志';


-- ===========================================================================
-- 二、客户关系
-- ===========================================================================

CREATE TABLE `client_profile` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`        BIGINT UNSIGNED          DEFAULT NULL COMMENT '关联登录账号，可为空（律师代录的线索客户）',
  `name`           VARCHAR(64)     NOT NULL              COMMENT '客户姓名 / 机构名称',
  `client_type`    ENUM('personal','company') NOT NULL DEFAULT 'personal' COMMENT '个人/机构',
  `id_no`          VARCHAR(255)             DEFAULT NULL COMMENT '证件号（加密存储，展示脱敏）',
  `gender`         VARCHAR(8)               DEFAULT NULL,
  `phone`          VARCHAR(20)              DEFAULT NULL,
  `address`        VARCHAR(255)             DEFAULT NULL,
  `source_channel` VARCHAR(32)              DEFAULT NULL COMMENT '来源渠道：转介绍/网络/门店',
  `level`          ENUM('vip','normal') NOT NULL DEFAULT 'normal' COMMENT '客户分级',
  `status`         ENUM('potential','deal','lost') NOT NULL DEFAULT 'potential' COMMENT '客户漏斗状态',
  `lawyer_id`      BIGINT UNSIGNED          DEFAULT NULL COMMENT '负责律师（owner）',
  `ai_profile`     JSON                     NULL         COMMENT 'AI客户画像：类型/诉求/风险点/跟进建议',
  `ai_profile_at`  DATETIME                 DEFAULT NULL COMMENT '画像生成时间',
  `remark`         TEXT                     NULL,
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_client_lawyer` (`lawyer_id`),
  KEY `ix_client_status` (`status`),
  KEY `ix_client_name`   (`name`),
  KEY `ix_client_user`   (`user_id`),
  CONSTRAINT `fk_client_user`   FOREIGN KEY (`user_id`)   REFERENCES `user` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_client_lawyer` FOREIGN KEY (`lawyer_id`) REFERENCES `user` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='客户扩展档案';

CREATE TABLE `follow_record` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `client_id`        BIGINT UNSIGNED NOT NULL COMMENT '客户',
  `user_id`          BIGINT UNSIGNED NOT NULL COMMENT '跟进人（律师）',
  `content`          TEXT            NOT NULL COMMENT '跟进内容',
  `method`           ENUM('phone','wechat','visit','email') NOT NULL DEFAULT 'phone' COMMENT '跟进方式',
  `next_follow_date` DATE                     DEFAULT NULL COMMENT '下次跟进日期',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_follow_client` (`client_id`),
  KEY `ix_follow_next`   (`next_follow_date`),
  CONSTRAINT `fk_follow_client` FOREIGN KEY (`client_id`) REFERENCES `client_profile` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_follow_user`   FOREIGN KEY (`user_id`)   REFERENCES `user` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='客户跟进记录';


-- ===========================================================================
-- 三、案件（业务核心）
-- ===========================================================================

CREATE TABLE `cases` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_no`        VARCHAR(64)     NOT NULL              COMMENT '案号 / 内部编号',
  `client_id`      BIGINT UNSIGNED NOT NULL              COMMENT '委托客户',
  `title`          VARCHAR(255)    NOT NULL              COMMENT '案件标题',
  `case_cause`     VARCHAR(64)              DEFAULT NULL COMMENT '案由',
  `case_type`      ENUM('litigation','non_litigation') NOT NULL DEFAULT 'litigation' COMMENT '诉讼/非诉',
  `court`          VARCHAR(255)             DEFAULT NULL COMMENT '受理法院/机构',
  `opposing_party` VARCHAR(255)             DEFAULT NULL COMMENT '对方当事人',
  `amount`         DECIMAL(12,2)   NOT NULL DEFAULT 0.00 COMMENT '标的额',
  `status`         ENUM('consulting','filed','handling','pending_close','closed','withdrawn')
                                    NOT NULL DEFAULT 'consulting' COMMENT '案件状态',
  `description`    TEXT                     NULL         COMMENT '案情描述',
  `created_by`     BIGINT UNSIGNED          DEFAULT NULL COMMENT '立案人',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `closed_at`      DATETIME                 DEFAULT NULL COMMENT '结案时间',
  `updated_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_case_no` (`case_no`),
  KEY `ix_case_client` (`client_id`),
  KEY `ix_case_status` (`status`),
  KEY `ix_case_type`   (`case_type`),
  KEY `ix_case_created` (`created_at`),
  CONSTRAINT `fk_case_client` FOREIGN KEY (`client_id`) REFERENCES `client_profile` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='案件表';

CREATE TABLE `case_lawyer` (
  `case_id`   BIGINT UNSIGNED NOT NULL,
  `lawyer_id` BIGINT UNSIGNED NOT NULL,
  `duty`      ENUM('lead','assist') NOT NULL DEFAULT 'lead' COMMENT '主办/协办',
  `created_at` DATETIME       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`case_id`,`lawyer_id`),
  KEY `ix_cl_lawyer` (`lawyer_id`),
  CONSTRAINT `fk_cl_case`   FOREIGN KEY (`case_id`)   REFERENCES `cases` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_cl_lawyer` FOREIGN KEY (`lawyer_id`) REFERENCES `user` (`id`)  ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='案件-律师关联（多对多）';

CREATE TABLE `case_event` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`     BIGINT UNSIGNED NOT NULL,
  `event_type`  ENUM('filing','accept','hearing','evidence','judgment','other')
                                NOT NULL DEFAULT 'other' COMMENT '节点类型',
  `event_date`  DATETIME        NOT NULL              COMMENT '节点时间',
  `description` VARCHAR(500)             DEFAULT NULL COMMENT '说明',
  `created_by`  BIGINT UNSIGNED          DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_event_case` (`case_id`,`event_date`),
  CONSTRAINT `fk_event_case` FOREIGN KEY (`case_id`) REFERENCES `cases` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='案件节点时间线';


-- ===========================================================================
-- 四、合同
-- ===========================================================================

CREATE TABLE `contract` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`          BIGINT UNSIGNED          DEFAULT NULL,
  `client_id`        BIGINT UNSIGNED NOT NULL,
  `name`             VARCHAR(255)    NOT NULL              COMMENT '合同名称',
  `contract_type`    VARCHAR(32)              DEFAULT NULL COMMENT '委托代理/风险代理/其他',
  `amount`           DECIMAL(12,2)   NOT NULL DEFAULT 0.00 COMMENT '合同金额',
  `start_date`       DATE                     DEFAULT NULL,
  `end_date`         DATE                     DEFAULT NULL,
  `status`           ENUM('draft','active','expired','terminated') NOT NULL DEFAULT 'draft',
  `file_url`         VARCHAR(500)             DEFAULT NULL COMMENT '合同文件路径',
  `ai_review_report` JSON                     NULL         COMMENT 'AI审查结果',
  `ai_review_at`     DATETIME                 DEFAULT NULL,
  `created_by`       BIGINT UNSIGNED          DEFAULT NULL,
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_contract_case`   (`case_id`),
  KEY `ix_contract_client` (`client_id`),
  KEY `ix_contract_end`    (`end_date`),
  KEY `ix_contract_status` (`status`),
  CONSTRAINT `fk_contract_case`   FOREIGN KEY (`case_id`)   REFERENCES `cases` (`id`)           ON DELETE SET NULL,
  CONSTRAINT `fk_contract_client` FOREIGN KEY (`client_id`) REFERENCES `client_profile` (`id`) ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='合同台账';


-- ===========================================================================
-- 五、收费
-- ===========================================================================

CREATE TABLE `fee_plan` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`      BIGINT UNSIGNED NOT NULL,
  `fee_type`     ENUM('fixed','ratio','risk','hourly') NOT NULL DEFAULT 'fixed' COMMENT '固定/比例/风险/计时',
  `total_amount` DECIMAL(12,2)   NOT NULL DEFAULT 0.00 COMMENT '收费总额',
  `description`  VARCHAR(500)             DEFAULT NULL,
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_plan_case` (`case_id`),
  CONSTRAINT `fk_plan_case` FOREIGN KEY (`case_id`) REFERENCES `cases` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收费方案';

CREATE TABLE `fee_period` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `fee_plan_id` BIGINT UNSIGNED NOT NULL,
  `period_no`   INT             NOT NULL DEFAULT 1      COMMENT '期次：1首期 2二期 3尾款',
  `due_amount`  DECIMAL(12,2)   NOT NULL DEFAULT 0.00   COMMENT '应收金额',
  `paid_amount` DECIMAL(12,2)   NOT NULL DEFAULT 0.00   COMMENT '已收金额（冗余，便于判定部分收款）',
  `due_date`    DATE                     DEFAULT NULL   COMMENT '应收日期',
  `status`      ENUM('unpaid','partial','paid') NOT NULL DEFAULT 'unpaid',
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_period_plan` (`fee_plan_id`),
  KEY `ix_period_due`  (`due_date`),
  KEY `ix_period_status` (`status`),
  CONSTRAINT `fk_period_plan` FOREIGN KEY (`fee_plan_id`) REFERENCES `fee_plan` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收费期次';

CREATE TABLE `payment` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `fee_period_id`  BIGINT UNSIGNED NOT NULL,
  `amount`         DECIMAL(12,2)   NOT NULL              COMMENT '本次实收金额',
  `pay_method`     VARCHAR(32)              DEFAULT NULL COMMENT '银行转账/现金/微信/支付宝',
  `receipt_no`     VARCHAR(64)              DEFAULT NULL COMMENT '收据号',
  `invoice_no`     VARCHAR(64)              DEFAULT NULL COMMENT '发票号',
  `invoice_title`  VARCHAR(255)             DEFAULT NULL COMMENT '开票抬头',
  `invoice_status` ENUM('none','applied','issued') NOT NULL DEFAULT 'none' COMMENT '未开票/申请中/已开票',
  `paid_at`        DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '收款时间',
  `source`         ENUM('offline','online') NOT NULL DEFAULT 'offline' COMMENT '收款来源：线下登记/在线支付',
  `order_no`       VARCHAR(40)              DEFAULT NULL COMMENT '关联支付订单号',
  `created_by`     BIGINT UNSIGNED          DEFAULT NULL COMMENT '登记人',
  `created_at`     DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_pay_period` (`fee_period_id`),
  KEY `ix_pay_time`   (`paid_at`),
  KEY `ix_pay_order`  (`order_no`),
  CONSTRAINT `fk_pay_period` FOREIGN KEY (`fee_period_id`) REFERENCES `fee_period` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='收款记录';

-- 沙箱支付订单：客户在线发起支付 → 支付成功后落一条 payment 记录
CREATE TABLE `payment_order` (
  `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `order_no`       VARCHAR(40)     NOT NULL              COMMENT '商户订单号（PAY + 时间 + 随机）',
  `fee_period_id`  BIGINT UNSIGNED NOT NULL              COMMENT '所属收费期次',
  `amount`         DECIMAL(12,2)   NOT NULL              COMMENT '应付金额',
  `channel`        VARCHAR(16)     NOT NULL              COMMENT '支付渠道：wechat/alipay/bank',
  `status`         ENUM('pending','paid','failed','cancelled','expired') NOT NULL DEFAULT 'pending',
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


-- ===========================================================================
-- 六、文书与模板
-- ===========================================================================

CREATE TABLE `doc_template` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `doc_type`   VARCHAR(32)     NOT NULL              COMMENT '文书类型：complaint/lawyer_letter/opinion...',
  `name`       VARCHAR(128)    NOT NULL              COMMENT '模板名称',
  `content`    LONGTEXT        NOT NULL              COMMENT '含 {变量} 占位符的正文',
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_tpl_type` (`doc_type`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文书模板';

CREATE TABLE `document` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`         BIGINT UNSIGNED          DEFAULT NULL,
  `client_id`       BIGINT UNSIGNED          DEFAULT NULL COMMENT '冗余，便于客户端直接查询',
  `doc_type`        VARCHAR(32)              DEFAULT NULL,
  `title`           VARCHAR(255)    NOT NULL,
  `content`         LONGTEXT                 NULL         COMMENT '富文本正文',
  `is_ai_generated` TINYINT         NOT NULL DEFAULT 0    COMMENT '是否AI生成',
  `ai_session_id`   BIGINT UNSIGNED          DEFAULT NULL,
  `file_url`        VARCHAR(500)             DEFAULT NULL COMMENT '导出的docx路径',
  `status`          ENUM('draft','final','published') NOT NULL DEFAULT 'draft' COMMENT 'published=客户可见',
  `created_by`      BIGINT UNSIGNED          DEFAULT NULL,
  `created_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_doc_case`   (`case_id`),
  KEY `ix_doc_client` (`client_id`),
  KEY `ix_doc_type`   (`doc_type`),
  CONSTRAINT `fk_doc_case`   FOREIGN KEY (`case_id`)   REFERENCES `cases` (`id`)           ON DELETE SET NULL,
  CONSTRAINT `fk_doc_client` FOREIGN KEY (`client_id`) REFERENCES `client_profile` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='文书库';


-- ===========================================================================
-- 七、日程、通知、留言、附件
-- ===========================================================================

CREATE TABLE `schedule` (
  `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`       BIGINT UNSIGNED          DEFAULT NULL,
  `client_id`     BIGINT UNSIGNED          DEFAULT NULL,
  `user_id`       BIGINT UNSIGNED NOT NULL              COMMENT '承办律师',
  `title`         VARCHAR(255)    NOT NULL,
  `schedule_type` ENUM('hearing','deadline','visit','meeting') NOT NULL DEFAULT 'hearing' COMMENT '开庭/期限/回访/会议',
  `event_date`    DATETIME        NOT NULL,
  `remind_at`     DATETIME                 DEFAULT NULL,
  `status`        ENUM('pending','done','cancelled') NOT NULL DEFAULT 'pending',
  `remark`        VARCHAR(500)             DEFAULT NULL,
  `created_at`    DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_sch_user`   (`user_id`,`event_date`),
  KEY `ix_sch_remind` (`remind_at`),
  KEY `ix_sch_case`   (`case_id`),
  CONSTRAINT `fk_sch_case` FOREIGN KEY (`case_id`) REFERENCES `cases` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='日程';

CREATE TABLE `notification` (
  `id`           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`      BIGINT UNSIGNED NOT NULL              COMMENT '接收人',
  `title`        VARCHAR(255)    NOT NULL,
  `content`      VARCHAR(1000)             DEFAULT NULL,
  `type`         VARCHAR(32)     NOT NULL DEFAULT 'system' COMMENT 'hearing/deadline/payment/follow/contract/system',
  `is_read`      TINYINT         NOT NULL DEFAULT 0,
  `related_type` VARCHAR(32)              DEFAULT NULL COMMENT 'case/schedule/contract',
  `related_id`   BIGINT UNSIGNED          DEFAULT NULL,
  `created_at`   DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_notify_user` (`user_id`,`is_read`),
  KEY `ix_notify_time` (`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='站内通知';

CREATE TABLE `message` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `case_id`     BIGINT UNSIGNED          DEFAULT NULL,
  `client_id`   BIGINT UNSIGNED NOT NULL,
  `lawyer_id`   BIGINT UNSIGNED          DEFAULT NULL COMMENT '会话对方的律师',
  `sender_id`   BIGINT UNSIGNED NOT NULL COMMENT '发送人',
  `sender_role` ENUM('client','lawyer') NOT NULL,
  `content`     TEXT                     NULL         COMMENT '正文（可只有附件）',
  `is_read`     TINYINT         NOT NULL DEFAULT 0,
  `is_deleted`  TINYINT         NOT NULL DEFAULT 0 COMMENT '是否已撤回/删除（软删除）',
  `deleted_at`  DATETIME                 DEFAULT NULL COMMENT '撤回/删除时间',
  `deleted_by`  BIGINT UNSIGNED          DEFAULT NULL COMMENT '操作人：发送人=撤回，管理员=后台删除',
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_msg_client` (`client_id`,`created_at`),
  KEY `ix_msg_lawyer` (`lawyer_id`,`is_read`),
  CONSTRAINT `fk_msg_client` FOREIGN KEY (`client_id`) REFERENCES `client_profile` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='沟通留言';

CREATE TABLE `attachment` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `biz_type`    VARCHAR(32)     NOT NULL              COMMENT 'case/contract/message/document',
  `biz_id`      BIGINT UNSIGNED NOT NULL              COMMENT '业务主键',
  `file_name`   VARCHAR(255)    NOT NULL              COMMENT '原始文件名',
  `file_path`   VARCHAR(500)    NOT NULL              COMMENT '相对存储路径',
  `file_size`   BIGINT          NOT NULL DEFAULT 0,
  `mime_type`   VARCHAR(128)             DEFAULT NULL,
  `uploader_id` BIGINT UNSIGNED          DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_att_biz` (`biz_type`,`biz_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='通用附件（证据/材料/合同文件）';


-- ===========================================================================
-- 八、AI 能力
-- ===========================================================================

CREATE TABLE `ai_session` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `user_id`    BIGINT UNSIGNED NOT NULL,
  `type`       ENUM('chat','document','contract','case','profile') NOT NULL DEFAULT 'chat',
  `related_id` BIGINT UNSIGNED          DEFAULT NULL COMMENT '关联案件/合同/客户ID',
  `title`      VARCHAR(255)             DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_ais_user` (`user_id`,`created_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI会话';

CREATE TABLE `ai_message` (
  `id`          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `session_id`  BIGINT UNSIGNED NOT NULL,
  `role`        ENUM('system','user','assistant') NOT NULL,
  `content`     LONGTEXT        NOT NULL,
  `refs`        JSON                     NULL         COMMENT '法条引用：[{law_name,article_no,content}]',
  `token_usage` INT                      DEFAULT NULL,
  `created_at`  DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_aim_session` (`session_id`,`id`),
  CONSTRAINT `fk_aim_session` FOREIGN KEY (`session_id`) REFERENCES `ai_session` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI消息记录';

CREATE TABLE `law_article` (
  `id`               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `law_name`         VARCHAR(64)     NOT NULL              COMMENT '法律名称：民法典/刑法...',
  `chapter`          VARCHAR(128)             DEFAULT NULL COMMENT '章节',
  `article_no`       VARCHAR(32)     NOT NULL              COMMENT '条号',
  `content`          TEXT            NOT NULL              COMMENT '条文原文',
  `effective_status` VARCHAR(16)     NOT NULL DEFAULT '有效',
  `vector_id`        VARCHAR(64)              DEFAULT NULL COMMENT 'Qdrant 中的向量点ID',
  `created_at`       DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_law_article` (`law_name`,`article_no`),
  KEY `ix_law_vector` (`vector_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='法律条文库';

CREATE TABLE `kb_document` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `title`      VARCHAR(255)    NOT NULL,
  `category`   VARCHAR(32)     NOT NULL DEFAULT 'faq' COMMENT 'faq/case_summary/manual',
  `content`    LONGTEXT        NOT NULL              COMMENT '知识片段正文',
  `vector_id`  VARCHAR(64)              DEFAULT NULL,
  `created_by` BIGINT UNSIGNED          DEFAULT NULL,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `ix_kb_cat` (`category`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='律所知识库（FAQ/案例摘要）';


-- ===========================================================================
-- 九、系统设置
-- ===========================================================================

CREATE TABLE `dict_item` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `dict_type`  VARCHAR(32)     NOT NULL              COMMENT 'case_cause/contract_type/doc_type/source_channel',
  `label`      VARCHAR(64)     NOT NULL              COMMENT '显示文本',
  `value`      VARCHAR(64)     NOT NULL              COMMENT '存储值',
  `sort`       INT             NOT NULL DEFAULT 0,
  `created_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_dict` (`dict_type`,`value`),
  KEY `ix_dict_type` (`dict_type`,`sort`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='数据字典';

CREATE TABLE `firm_info` (
  `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `name`       VARCHAR(128)    NOT NULL DEFAULT '示例律师事务所',
  `logo`       VARCHAR(255)             DEFAULT NULL,
  `address`    VARCHAR(255)             DEFAULT NULL,
  `phone`      VARCHAR(32)              DEFAULT NULL,
  `intro`      TEXT                     NULL,
  `updated_at` DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='律所信息（单行）';

CREATE TABLE `ai_config` (
  `id`              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  `provider`        VARCHAR(32)     NOT NULL DEFAULT 'deepseek',
  `base_url`        VARCHAR(255)    NOT NULL,
  `api_key`         VARCHAR(255)             DEFAULT NULL,
  `model`           VARCHAR(64)     NOT NULL,
  `temperature`     DECIMAL(3,2)    NOT NULL DEFAULT 0.30,
  `embedding_model` VARCHAR(64)              DEFAULT NULL,
  `status`          TINYINT         NOT NULL DEFAULT 0    COMMENT '1=启用（优先于 .env）',
  `updated_at`      DATETIME        NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='AI配置（管理员页面可改）';


SET FOREIGN_KEY_CHECKS = 1;


-- ===========================================================================
-- 十、初始数据
-- ===========================================================================

-- 默认管理员：admin / admin123（首次登录后请立即改密码）
INSERT INTO `user` (`username`, `password_hash`, `real_name`, `role`, `status`) VALUES
('admin', '$2b$12$ihvQZ0FyLW0XrBPSaCkAxO1vDa76KEiDqv3Z7/f5UVlwVvCioe6m6', '系统管理员', 'admin', 1);

INSERT INTO `firm_info` (`name`, `address`, `phone`, `intro`) VALUES
('示例律师事务所', 'XX市XX区XX路1号', '010-00000000', '本系统演示用律所信息，可在管理端修改。');

-- AI 配置留空行，管理员在页面上填写 Key 后置 status=1 生效
INSERT INTO `ai_config` (`provider`, `base_url`, `model`, `temperature`, `embedding_model`, `status`) VALUES
('deepseek', 'https://api.deepseek.com/v1', 'deepseek-chat', 0.30, 'text-embedding-3-small', 0);

-- 数据字典：案由
INSERT INTO `dict_item` (`dict_type`, `label`, `value`, `sort`) VALUES
('case_cause', '合同纠纷',   'contract_dispute',   10),
('case_cause', '民间借贷',   'loan_dispute',       20),
('case_cause', '婚姻家庭',   'marriage_family',    30),
('case_cause', '劳动争议',   'labor_dispute',      40),
('case_cause', '侵权责任',   'tort',               50),
('case_cause', '房屋买卖',   'real_estate',        60),
('case_cause', '股权纠纷',   'equity_dispute',     70),
('case_cause', '刑事辩护',   'criminal_defense',   80),
('case_cause', '行政处罚',   'admin_penalty',      90);

-- 数据字典：合同类型
INSERT INTO `dict_item` (`dict_type`, `label`, `value`, `sort`) VALUES
('contract_type', '委托代理合同', 'agency',      10),
('contract_type', '风险代理合同', 'risk_agency', 20),
('contract_type', '法律顾问合同', 'counsel',     30),
('contract_type', '其他',         'other',       90);

-- 数据字典：文书类型
INSERT INTO `dict_item` (`dict_type`, `label`, `value`, `sort`) VALUES
('doc_type', '起诉状',     'complaint',      10),
('doc_type', '答辩状',     'response',       20),
('doc_type', '律师函',     'lawyer_letter',  30),
('doc_type', '法律意见书', 'opinion',        40),
('doc_type', '委托书',     'poa',            50),
('doc_type', '代理词',     'agency_argument',60);

-- 数据字典：客户来源
INSERT INTO `dict_item` (`dict_type`, `label`, `value`, `sort`) VALUES
('source_channel', '转介绍', 'referral', 10),
('source_channel', '网络',   'online',   20),
('source_channel', '门店',   'walk_in',  30),
('source_channel', '老客户', 'repeat',   40);
