<template>
  <div class="home">
    <div class="welcome-card">
      <div class="welcome-text">
        <h2>{{ greeting }}，{{ userStore.realName }}</h2>
        <p>
          今天是 {{ today }}，{{
            kpi.today_todos ? `今天有 ${kpi.today_todos} 项待办` : '今天暂无待办事项'
          }}
        </p>
      </div>
      <div class="welcome-badge">执业律师</div>
    </div>

    <StatCards :items="stats" :columns="3" :loading="statLoading" />

    <!-- ============ 待办 ============ -->
    <div class="todo-grid">
      <el-card shadow="never" class="todo-card">
        <template #header>
          <div class="card-head">
            <span class="head-title">
              今日待办
              <span class="count-badge">{{ todayList.length }}</span>
            </span>
            <el-button link type="primary" size="small" @click="goSchedule()">
              打开日程<el-icon class="arrow"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </template>

        <div v-loading="todayLoading" class="todo-body">
          <el-empty
            v-if="!todayLoading && !todayList.length"
            description="今天没有安排，可安心处理案件"
            :image-size="64"
          />
          <div
            v-for="e in todayList"
            :key="e.id"
            class="todo-item"
            :class="{ done: e.status === 'done', cancelled: e.status === 'cancelled' }"
            @click="goSchedule(e.event_date)"
          >
            <span class="todo-time">{{ timeOf(e.event_date) || '全天' }}</span>
            <span class="type-pill" :style="pillStyle(e.schedule_type)">
              {{ typeMeta(e.schedule_type).label }}
            </span>
            <span class="todo-title">{{ e.title }}</span>
            <el-tag v-if="e.status === 'done'" type="success" size="small" effect="plain">
              已完成
            </el-tag>
          </div>
        </div>
      </el-card>

      <el-card shadow="never" class="todo-card">
        <template #header>
          <div class="card-head">
            <span class="head-title">
              未来 7 天
              <span class="count-badge">{{ upcoming.length }}</span>
            </span>
            <el-button link type="primary" size="small" @click="goSchedule(null, 'week')">
              周日历<el-icon class="arrow"><ArrowRight /></el-icon>
            </el-button>
          </div>
        </template>

        <div v-loading="upcomingLoading" class="todo-body">
          <el-empty
            v-if="!upcomingLoading && !upcoming.length"
            description="未来一周暂无待办日程"
            :image-size="64"
          />
          <div
            v-for="e in upcoming"
            :key="e.id"
            class="todo-item"
            @click="goSchedule(e.event_date)"
          >
            <span class="todo-time">{{ monthDay(e.event_date) }}</span>
            <span class="type-pill" :style="pillStyle(e.schedule_type)">
              {{ typeMeta(e.schedule_type).label }}
            </span>
            <span class="todo-title">{{ e.title }}</span>
            <span v-if="e.case_no" class="todo-case">{{ e.case_no }}</span>
          </div>
        </div>
      </el-card>
    </div>

    <!-- ============ 提醒 ============ -->
    <el-card shadow="never" class="todo-card">
      <template #header>
        <div class="card-head">
          <span class="head-title">
            最新提醒
            <span v-if="unread" class="count-badge danger">{{ unread }}</span>
          </span>
          <el-button link type="primary" size="small" @click="goNotifications">
            通知中心<el-icon class="arrow"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>

      <div v-loading="noticeLoading" class="notice-body">
        <el-empty
          v-if="!noticeLoading && !notices.length"
          description="暂无提醒，定时任务会在开庭、缴费、合同到期前自动推送"
          :image-size="64"
        />
        <div v-for="n in notices" :key="n.id" class="notice-item" :class="{ unread: !n.is_read }">
          <div
            class="notice-icon"
            :style="{ background: noticeMeta(n.type).bg, color: noticeMeta(n.type).color }"
          >
            <el-icon :size="14"><component :is="noticeMeta(n.type).icon" /></el-icon>
          </div>
          <span class="notice-title">{{ n.title }}</span>
          <span class="notice-rel">{{ relativeTime(n.created_at) }}</span>
        </div>
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { useUserStore } from '@/stores/user'
import { getTodaySchedules, getUpcomingSchedules } from '@/api/schedule'
import { listNotifications } from '@/api/notifications'
import { getMyStats } from '@/api/stats'
import StatCards from '@/components/StatCards.vue'
import {
  dateKey,
  fmtMonthDay,
  noticeMeta,
  relativeTime,
  timeOf,
  typeMeta,
} from '@/utils/schedule'

const router = useRouter()
const userStore = useUserStore()

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 6) return '夜深了'
  if (h < 12) return '早上好'
  if (h < 14) return '中午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const today = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
})

// ---------- 个人统计（/api/stats/my） ----------
const stat = ref(null)
const statLoading = ref(false)

const kpi = computed(() => stat.value?.kpi || {})

function money(v) {
  return `¥${Number(v || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

const stats = computed(() => [
  {
    label: '在办案件',
    value: Number(kpi.value.active_cases || 0).toLocaleString('zh-CN'),
    unit: '件',
    icon: 'Suitcase',
    tone: 'navy',
    hint: `累计承办 ${kpi.value.total_cases ?? 0} 件`,
  },
  {
    label: '本月创收',
    value: money(kpi.value.month_income),
    icon: 'Money',
    tone: 'gold',
    hint: `本年 ${money(kpi.value.year_income)}`,
  },
  {
    label: '未来 7 天待办',
    value: Number(kpi.value.week_todos || 0).toLocaleString('zh-CN'),
    unit: '项',
    icon: 'Calendar',
    tone: 'slate',
    hint: `今日 ${kpi.value.today_todos ?? 0} 项`,
  },
])

// ---------- 待办 ----------
const todayList = ref([])
const todayLoading = ref(false)
const upcoming = ref([])
const upcomingLoading = ref(false)

// ---------- 提醒 ----------
const notices = ref([])
const unread = ref(0)
const noticeLoading = ref(false)

function pillStyle(type) {
  const meta = typeMeta(type)
  return { background: meta.bg, color: meta.color }
}

function monthDay(value) {
  return fmtMonthDay(value).replace('日', '')
}

function goSchedule(date, view) {
  const query = {}
  if (date) query.date = dateKey(date)
  if (view) query.view = view
  router.push({ path: '/lawyer/schedule', query })
}

function goNotifications() {
  router.push('/lawyer/notifications')
}

async function loadStat() {
  statLoading.value = true
  try {
    stat.value = await getMyStats({ months: 6 })
  } catch {
    stat.value = null
  } finally {
    statLoading.value = false
  }
}

async function loadToday() {
  todayLoading.value = true
  try {
    todayList.value = (await getTodaySchedules()) || []
  } catch {
    todayList.value = []
  } finally {
    todayLoading.value = false
  }
}

async function loadUpcoming() {
  upcomingLoading.value = true
  try {
    upcoming.value = (await getUpcomingSchedules(7)) || []
  } catch {
    upcoming.value = []
  } finally {
    upcomingLoading.value = false
  }
}

async function loadNotices() {
  noticeLoading.value = true
  try {
    const data = await listNotifications({ page: 1, page_size: 5 })
    notices.value = data.items || []
    unread.value = data.unread || 0
  } catch {
    notices.value = []
  } finally {
    noticeLoading.value = false
  }
}

loadStat()
loadToday()
loadUpcoming()
loadNotices()
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.welcome-card {
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 60%, var(--brand-navy-deep) 100%);
  border-radius: 12px;
  padding: 28px 32px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.welcome-text h2 {
  margin: 0 0 8px;
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 1px;
}

.welcome-text p {
  margin: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
  letter-spacing: 0.5px;
}

.welcome-badge {
  padding: 6px 16px;
  border: 1px solid rgba(201, 165, 92, 0.5);
  border-radius: 20px;
  color: var(--brand-gold-light);
  font-size: 12px;
  letter-spacing: 2px;
}

/* ---------- 待办 ---------- */
.todo-grid {
  display: grid;
  grid-template-columns: 1.15fr 1fr;
  gap: 16px;
}

.todo-card {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.head-title {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.count-badge {
  font-size: 11px;
  font-weight: 500;
  color: var(--brand-muted);
  background: #f0f2f6;
  border-radius: 9px;
  padding: 1px 7px;
}

.count-badge.danger {
  color: #fff;
  background: var(--el-color-danger);
}

.arrow {
  margin-left: 2px;
  font-size: 12px;
}

.todo-body {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 152px;
  max-height: 300px;
  overflow-y: auto;
}

.todo-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s, background 0.15s;
  font-size: 13px;
}

.todo-item:hover {
  background: #f7f8fb;
  border-color: #d5dae6;
}

.todo-item.done {
  opacity: 0.6;
}

.todo-item.done .todo-title {
  text-decoration: line-through;
}

.todo-item.cancelled {
  opacity: 0.45;
  text-decoration: line-through;
}

.todo-time {
  flex-shrink: 0;
  width: 56px;
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
}

.type-pill {
  flex-shrink: 0;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 11px;
  line-height: 18px;
}

.todo-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--brand-text);
}

.todo-case {
  font-size: 11px;
  color: var(--brand-muted);
  flex-shrink: 0;
}

/* ---------- 提醒 ---------- */
.notice-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-height: 70px;
  max-height: 300px;
  overflow-y: auto;
}

.notice-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: 8px;
  font-size: 13px;
}

.notice-item.unread {
  background: #fdfbf6;
}

.notice-icon {
  width: 26px;
  height: 26px;
  border-radius: 7px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.notice-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--brand-text);
}

.notice-rel {
  font-size: 12px;
  color: var(--brand-muted);
  flex-shrink: 0;
}

@media (max-width: 1100px) {
  .todo-grid {
    grid-template-columns: 1fr;
  }
}
</style>
