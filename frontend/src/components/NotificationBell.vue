<template>
  <el-popover
    placement="bottom-end"
    :width="384"
    trigger="click"
    :show-arrow="false"
    popper-class="notice-popper"
    @show="onShow"
  >
    <template #reference>
      <div class="bell-chip" :class="{ 'has-unread': unread > 0 }" title="通知中心">
        <el-badge :value="unread" :max="99" :hidden="!unread" class="bell-badge">
          <el-icon :size="18"><Bell /></el-icon>
        </el-badge>
      </div>
    </template>

    <div class="notice-panel">
      <div class="panel-head">
        <span class="panel-title">通知中心</span>
        <div class="head-actions">
          <span v-if="unread" class="unread-count">{{ unread }} 条未读</span>
          <el-button v-if="unread" link type="primary" size="small" @click="readAll">
            全部已读
          </el-button>
        </div>
      </div>

      <div v-loading="loading" class="panel-list">
        <el-empty v-if="!loading && !items.length" description="暂无通知" :image-size="70" />
        <div
          v-for="n in items"
          :key="n.id"
          class="notice-item"
          :class="{ unread: !n.is_read }"
          @click="openItem(n)"
        >
          <div
            class="notice-icon"
            :style="{ background: noticeMeta(n.type).bg, color: noticeMeta(n.type).color }"
          >
            <el-icon :size="15"><component :is="noticeMeta(n.type).icon" /></el-icon>
          </div>
          <div class="notice-main">
            <div class="notice-title">{{ n.title }}</div>
            <div v-if="n.content" class="notice-content">{{ n.content }}</div>
            <div class="notice-meta">
              <span class="notice-type" :style="{ color: noticeMeta(n.type).color }">
                {{ n.type_label }}
              </span>
              <span class="notice-time">{{ relativeTime(n.created_at) }}</span>
            </div>
          </div>
          <span v-if="!n.is_read" class="unread-dot" />
        </div>
      </div>

      <div class="panel-foot">
        <el-button link type="primary" size="small" @click="goAll">
          查看全部通知
          <el-icon class="foot-arrow"><ArrowRight /></el-icon>
        </el-button>
      </div>
    </div>
  </el-popover>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowRight, Bell } from '@element-plus/icons-vue'
import {
  getMyUnreadCount,
  getUnreadCount,
  listMyNotifications,
  listNotifications,
  markAllRead,
  markMyAllRead,
  markMyRead,
  markRead,
} from '@/api/notifications'
import { noticeMeta, relativeTime } from '@/utils/schedule'
import { useUserStore } from '@/stores/user'

const userStore = useUserStore()
const router = useRouter()
const route = useRoute()

// 客户端只拉取对外通知，律师/管理员拉取全部
const isClient = computed(() => userStore.role === 'client')

const unread = ref(0)
const items = ref([])
const loading = ref(false)
let timer = null

const PREVIEW_SIZE = 8

async function fetchUnread() {
  try {
    const res = isClient.value ? await getMyUnreadCount() : await getUnreadCount()
    unread.value = Number(res?.count || 0)
  } catch {
    /* 未登录/网络异常时静默，不打扰用户 */
  }
}

async function fetchList() {
  loading.value = true
  try {
    const params = { page: 1, page_size: PREVIEW_SIZE }
    const data = isClient.value
      ? await listMyNotifications(params)
      : await listNotifications(params)
    items.value = data.items || []
    unread.value = Number(data.unread || 0)
  } catch {
    items.value = []
  } finally {
    loading.value = false
  }
}

function onShow() {
  fetchList()
}

async function openItem(n) {
  if (n.is_read) return
  // 先本地置已读，避免整段刷新造成闪烁
  n.is_read = true
  unread.value = Math.max(0, unread.value - 1)
  try {
    await (isClient.value ? markMyRead(n.id) : markRead(n.id))
  } catch {
    fetchList()
  }
}

async function readAll() {
  try {
    const res = isClient.value ? await markMyAllRead() : await markAllRead()
    items.value = items.value.map((i) => ({ ...i, is_read: true }))
    unread.value = 0
    ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  } catch {
    fetchList()
  }
}

function goAll() {
  const base = isClient.value
    ? '/client'
    : route.path.startsWith('/admin')
      ? '/admin'
      : '/lawyer'
  router.push(`${base}/notifications`)
}

// 切换页面时同步一次未读数（例如刚在通知页点过已读）
watch(
  () => route.path,
  () => fetchUnread(),
)

onMounted(() => {
  fetchUnread()
  // 轮询未读数，让定时任务生成的新提醒尽量及时出现在红点上
  timer = setInterval(fetchUnread, 60000)
})

onBeforeUnmount(() => {
  if (timer) clearInterval(timer)
})
</script>

<style scoped>
.bell-chip {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--brand-ink);
  transition: background 0.15s, color 0.15s;
  margin-right: 6px;
}

.bell-chip:hover {
  background: var(--brand-bg);
  color: var(--brand-gold-deep);
}

.bell-chip.has-unread {
  color: var(--brand-gold-deep);
}

.bell-badge :deep(.el-badge__content) {
  font-size: 10px;
  height: 15px;
  line-height: 15px;
  padding: 0 4px;
  border: none;
}

/* ---------- 面板 ---------- */
.notice-panel {
  margin: -12px;
}

.panel-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-bottom: 1px solid var(--brand-line);
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.unread-count {
  font-size: 12px;
  color: var(--brand-muted);
}

.panel-list {
  max-height: 384px;
  overflow-y: auto;
  padding: 4px 0;
}

.notice-item {
  display: flex;
  gap: 10px;
  padding: 10px 16px 10px 14px;
  cursor: pointer;
  position: relative;
  border-left: 2px solid transparent;
  transition: background 0.15s;
}

.notice-item:hover {
  background: #f7f8fb;
}

.notice-item.unread {
  background: #fdfbf6;
  border-left-color: var(--brand-gold);
}

.notice-item.unread:hover {
  background: #fbf7ee;
}

.notice-icon {
  width: 30px;
  height: 30px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  margin-top: 2px;
}

.notice-main {
  min-width: 0;
  flex: 1;
}

.notice-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--brand-ink);
  line-height: 1.5;
  word-break: break-all;
}

.notice-content {
  margin-top: 3px;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
}

.notice-meta {
  margin-top: 6px;
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 11px;
}

.notice-type {
  font-weight: 500;
}

.notice-time {
  color: var(--brand-muted);
}

.unread-dot {
  position: absolute;
  right: 12px;
  top: 16px;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--el-color-danger);
}

.panel-foot {
  border-top: 1px solid var(--brand-line);
  padding: 8px 16px;
  display: flex;
  justify-content: center;
}

.foot-arrow {
  margin-left: 2px;
  font-size: 12px;
}

:global(.notice-popper) {
  padding: 12px !important;
  border-radius: 12px;
}
</style>
