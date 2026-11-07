<template>
  <div class="notifications-page">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-radio-group v-model="filter" size="default" @change="search">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button value="unread">
          未读<span v-if="unread" class="tab-count">{{ unread }}</span>
        </el-radio-button>
        <el-radio-button value="read">已读</el-radio-button>
      </el-radio-group>

      <el-select
        v-model="typeFilter"
        placeholder="全部类型"
        clearable
        class="type-sel"
        @change="search"
      >
        <el-option
          v-for="(m, k) in NOTIFICATION_TYPE_META"
          :key="k"
          :label="m.label"
          :value="k"
        />
      </el-select>

      <div class="spacer" />

      <el-button v-if="isAdmin" plain :loading="scanning" @click="scan">
        <el-icon><Refresh /></el-icon>立即扫描提醒
      </el-button>
      <el-button :disabled="!unread" @click="readAll">
        <el-icon><Select /></el-icon>全部标为已读
      </el-button>
    </div>

    <!-- 通知列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="类型" width="132">
          <template #default="{ row }">
            <span class="type-pill" :style="pillStyle(row.type)">
              {{ noticeMeta(row.type).label }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="通知内容" min-width="320">
          <template #default="{ row }">
            <div class="content-cell">
              <div class="content-title">
                <span v-if="!row.is_read" class="dot" />
                {{ row.title }}
              </div>
              <div v-if="row.content" class="content-text">{{ row.content }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="时间" width="160">
          <template #default="{ row }">
            <div class="time-cell">
              <span>{{ relativeTime(row.created_at) }}</span>
              <span class="time-abs">{{ fmtDateTime(row.created_at) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.is_read" type="info" size="small" effect="plain">已读</el-tag>
            <el-tag v-else type="danger" size="small" effect="light">未读</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="130" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="!row.is_read" link type="primary" size="small" @click="readOne(row)">
              标为已读
            </el-button>
            <el-button link type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !rows.length"
        :description="filter === 'unread' ? '没有未读通知' : '暂无通知'"
        :image-size="100"
      />

      <div v-if="total > 0" class="pager">
        <el-pagination
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Refresh, Select } from '@element-plus/icons-vue'
import {
  deleteNotification,
  listNotifications,
  markAllRead,
  markRead,
  scanReminders,
} from '@/api/notifications'
import { NOTIFICATION_TYPE_META, fmtDateTime, noticeMeta, relativeTime } from '@/utils/schedule'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const isAdmin = computed(() => userStore.role === 'admin')

const rows = ref([])
const total = ref(0)
const unread = ref(0)
const loading = ref(false)
const scanning = ref(false)

const filter = ref('all')
const typeFilter = ref('')
const page = ref(1)
const pageSize = ref(20)

function pillStyle(type) {
  const meta = noticeMeta(type)
  return { background: meta.bg, color: meta.color }
}

async function load() {
  loading.value = true
  try {
    const params = { page: page.value, page_size: pageSize.value }
    if (filter.value === 'unread') params.is_read = false
    if (filter.value === 'read') params.is_read = true
    if (typeFilter.value) params.type = typeFilter.value
    const data = await listNotifications(params)
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

async function readOne(row) {
  await markRead(row.id)
  row.is_read = true
  unread.value = Math.max(0, unread.value - 1)
  if (filter.value === 'unread') load()
}

async function readAll() {
  const res = await markAllRead()
  ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  load()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除通知「${row.title}」吗？`, '删除通知', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteNotification(row.id)
  ElMessage.success('通知已删除')
  load()
}

async function scan() {
  scanning.value = true
  try {
    const res = await scanReminders()
    ElMessage.success(
      `扫描完成：日程 ${res.schedule} 条、缴费 ${res.payment} 条、跟进 ${res.follow} 条、合同 ${res.contract} 条`,
    )
    search()
  } finally {
    scanning.value = false
  }
}

load()
</script>

<style scoped>
.notifications-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: var(--el-color-danger);
}

.type-sel {
  width: 150px;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.type-pill {
  display: inline-block;
  border-radius: 4px;
  padding: 1px 8px;
  font-size: 12px;
  line-height: 20px;
  white-space: nowrap;
}

.content-cell {
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 4px 0;
}

.content-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--brand-ink);
  display: flex;
  align-items: center;
  gap: 6px;
}

.dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-danger);
  flex-shrink: 0;
}

.content-text {
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.6;
  white-space: pre-wrap;
}

.time-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
  font-size: 13px;
  color: var(--brand-text);
}

.time-abs {
  font-size: 11px;
  color: var(--brand-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
