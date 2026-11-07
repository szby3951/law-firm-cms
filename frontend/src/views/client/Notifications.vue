<template>
  <div class="client-notice">
    <!-- 概览 -->
    <div class="summary">
      <div class="summary-left">
        <div class="summary-icon">
          <el-icon :size="22"><Bell /></el-icon>
        </div>
        <div>
          <div class="summary-title">消息通知</div>
          <div class="summary-sub">
            开庭、期限与缴费提醒会在这里通知您，共 {{ total }} 条<span v-if="unread">，其中 {{ unread }} 条未读</span>
          </div>
        </div>
      </div>
      <el-button :disabled="!unread" type="primary" plain @click="readAll">
        <el-icon><Select /></el-icon>全部标为已读
      </el-button>
    </div>

    <!-- 筛选 -->
    <div class="filter-bar">
      <el-radio-group v-model="filter" size="default" @change="search">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="unread">
          未读<span v-if="unread" class="tab-count">{{ unread }}</span>
        </el-radio-button>
      </el-radio-group>
      <span class="filter-tip">仅显示与您本人案件相关的提醒</span>
    </div>

    <!-- 通知卡片 -->
    <div v-loading="loading" class="notice-list">
      <el-empty
        v-if="!loading && !rows.length"
        :description="filter === 'unread' ? '没有未读通知' : '暂无通知'"
        :image-size="100"
      />

      <div
        v-for="n in rows"
        :key="n.id"
        class="notice-card"
        :class="{ unread: !n.is_read }"
      >
        <div
          class="notice-icon"
          :style="{ background: noticeMeta(n.type).bg, color: noticeMeta(n.type).color }"
        >
          <el-icon :size="18"><component :is="noticeMeta(n.type).icon" /></el-icon>
        </div>

        <div class="notice-body">
          <div class="notice-head">
            <span class="notice-title">{{ n.title }}</span>
            <span class="type-pill" :style="{ background: noticeMeta(n.type).bg, color: noticeMeta(n.type).color }">
              {{ n.type_label }}
            </span>
            <span v-if="!n.is_read" class="unread-flag">未读</span>
          </div>
          <div v-if="n.content" class="notice-content">{{ n.content }}</div>
          <div class="notice-foot">
            <span class="notice-time">{{ fmtDateTime(n.created_at) }}</span>
            <span class="notice-rel">{{ relativeTime(n.created_at) }}</span>
            <div class="grow" />
            <el-button
              v-if="!n.is_read"
              link
              type="primary"
              size="small"
              @click="readOne(n)"
            >
              标为已读
            </el-button>
            <span v-else class="read-flag">已读</span>
          </div>
        </div>
      </div>

      <div v-if="total > pageSize" class="pager">
        <el-pagination
          v-model:current-page="page"
          :page-size="pageSize"
          :total="total"
          layout="prev, pager, next"
          background
          size="small"
          @current-change="load"
        />
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Bell, Select } from '@element-plus/icons-vue'
import { listMyNotifications, markMyAllRead, markMyRead } from '@/api/notifications'
import { fmtDateTime, noticeMeta, relativeTime } from '@/utils/schedule'

const rows = ref([])
const total = ref(0)
const unread = ref(0)
const loading = ref(false)

const filter = ref('all')
const page = ref(1)
const pageSize = ref(10)

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filter.value === 'unread') params.is_read = false
    const data = await listMyNotifications(params)
    rows.value = data.items || []
    total.value = data.total || 0
    unread.value = data.unread || 0
  } finally {
    loading.value = false
  }
}

function search() {
  page.value = 1
  load()
}

async function readOne(n) {
  await markMyRead(n.id)
  n.is_read = true
  unread.value = Math.max(0, unread.value - 1)
  if (filter.value === 'unread') load()
}

async function readAll() {
  const res = await markMyAllRead()
  ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  load()
}

load()
</script>

<style scoped>
.client-notice {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 概览 ---------- */
.summary {
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 60%, var(--brand-navy-deep) 100%);
  border-radius: 12px;
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: #fff;
}

.summary-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.12);
  color: var(--brand-gold-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.summary-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
}

.summary-sub {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

/* ---------- 筛选 ---------- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: var(--el-color-danger);
}

.filter-tip {
  font-size: 12px;
  color: var(--brand-muted);
}

/* ---------- 通知卡片 ---------- */
.notice-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 120px;
}

.notice-card {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-left: 3px solid transparent;
  border-radius: 12px;
  padding: 16px 18px;
  display: flex;
  gap: 14px;
}

.notice-card.unread {
  border-left-color: var(--brand-gold);
  background: #fdfbf6;
}

.notice-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.notice-body {
  flex: 1;
  min-width: 0;
}

.notice-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.notice-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.type-pill {
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 11px;
  line-height: 18px;
}

.unread-flag {
  font-size: 11px;
  color: var(--el-color-danger);
  border: 1px solid rgba(245, 108, 108, 0.35);
  border-radius: 4px;
  padding: 0 5px;
  line-height: 16px;
}

.notice-content {
  margin-top: 8px;
  font-size: 13px;
  color: var(--brand-text);
  line-height: 1.75;
  white-space: pre-wrap;
}

.notice-foot {
  margin-top: 10px;
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--brand-muted);
}

.notice-time {
  color: var(--brand-muted);
}

.notice-rel {
  color: #b3b9c6;
}

.grow {
  flex: 1;
}

.read-flag {
  font-size: 12px;
  color: var(--brand-muted);
}

.pager {
  display: flex;
  justify-content: center;
  margin-top: 4px;
}
</style>
