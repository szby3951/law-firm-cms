-- ===========================================================================
-- 留言软删除：撤回（发送人 5 分钟内）与管理员删除
--
-- 作用：给 `message` 增加三个字段，支持「撤回后对方看到占位」而不是记录消失。
--       正文与附件仍留在库里（审计与误删恢复），只是不再通过接口下发。
--
-- 幂等：本文件由 scripts/migrate_message_soft_delete.py 执行，脚本内先查
--       information_schema 判断列是否已存在，重复执行安全。
--
-- 注意：**不要**在已有数据的生产库上执行 db/schema.sql（开头有 DROP TABLE）。
--       生产只跑本文件或对应的 python 脚本。
-- ===========================================================================

ALTER TABLE `message`
  ADD COLUMN `is_deleted` TINYINT NOT NULL DEFAULT 0
      COMMENT '是否已撤回/删除（软删除，正文与附件不再下发）' AFTER `is_read`,
  ADD COLUMN `deleted_at` DATETIME DEFAULT NULL
      COMMENT '撤回/删除时间' AFTER `is_deleted`,
  ADD COLUMN `deleted_by` BIGINT UNSIGNED DEFAULT NULL
      COMMENT '操作人：发送人本人=撤回，管理员=后台删除' AFTER `deleted_at`;

-- 会话列表/未读统计都会带 is_deleted 过滤，数据量大时可加索引；
-- 本系统单客户会话通常在千条以内，暂不建索引（避免写放大）。
