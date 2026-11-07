<template>
  <div class="schedule-page">
    <!-- ============ 概览 ============ -->
    <div class="stat-row">
      <div v-for="s in statCards" :key="s.label" class="stat-card">
        <div class="stat-icon" :style="{ background: s.bg, color: s.color }">
          <el-icon :size="20"><component :is="s.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value" :class="{ danger: s.danger }">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- ============ 工具条 ============ -->
    <div class="toolbar">
      <div class="period-nav">
        <el-button text circle class="nav-btn" @click="shift(-1)">
          <el-icon><ArrowLeft /></el-icon>
        </el-button>
        <span class="period-text">{{ periodLabel }}</span>
        <el-button text circle class="nav-btn" @click="shift(1)">
          <el-icon><ArrowRight /></el-icon>
        </el-button>
        <el-button size="small" class="today-btn" @click="goToday">今天</el-button>
      </div>

      <el-radio-group v-model="view" @change="onViewChange">
        <el-radio-button value="month">月</el-radio-button>
        <el-radio-button value="week">周</el-radio-button>
        <el-radio-button value="day">日</el-radio-button>
      </el-radio-group>

      <el-select
        v-model="typeFilter"
        placeholder="全部类型"
        clearable
        size="default"
        class="type-sel"
      >
        <el-option v-for="t in SCHEDULE_TYPE_OPTIONS" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>

      <div class="spacer" />

      <el-button type="primary" @click="openCreate(selectedKey)">
        <el-icon><Plus /></el-icon>新建日程
      </el-button>
    </div>

    <!-- ============ 主体：日历 + 当日清单 ============ -->
    <div class="body" :class="{ wide: view === 'day' }">
      <el-card shadow="never" class="cal-card" v-loading="loading">
        <template #header>
          <div class="card-head">
            <span>{{ viewTitle }}</span>
            <div class="legend">
              <span v-for="t in SCHEDULE_TYPE_OPTIONS" :key="t.value" class="legend-item">
                <i class="legend-dot" :style="{ background: SCHEDULE_TYPE_META[t.value].color }" />
                {{ t.label }}
              </span>
            </div>
          </div>
        </template>

        <!-- ---------- 月视图 ---------- -->
        <div v-if="view === 'month'" class="month-view">
          <div class="weekday-row">
            <span v-for="w in WEEKDAYS" :key="w" class="weekday">{{ w }}</span>
          </div>
          <div class="month-grid">
            <div
              v-for="cell in monthCells"
              :key="cell.key"
              class="day-cell"
              :class="{
                other: !cell.inMonth,
                today: cell.isToday,
                selected: cell.key === selectedKey,
                weekend: cell.weekend,
              }"
              @click="selectDay(cell)"
              @dblclick="openCreate(cell.key)"
            >
              <div class="day-head">
                <span class="day-num">{{ cell.day }}</span>
                <span v-if="cell.events.length" class="day-count">{{ cell.events.length }}</span>
              </div>
              <div class="day-events">
                <div
                  v-for="e in cell.events.slice(0, 3)"
                  :key="e.id"
                  class="event-chip"
                  :class="{ done: e.status === 'done', cancelled: e.status === 'cancelled' }"
                  :style="chipStyle(e)"
                  :title="`${timeOf(e.event_date)} ${e.title}`"
                  @click.stop="selectDay(cell)"
                >
                  <span class="chip-time">{{ timeOf(e.event_date) }}</span>
                  <span class="chip-title">{{ e.title }}</span>
                </div>
                <div v-if="cell.events.length > 3" class="more-text">
                  +{{ cell.events.length - 3 }} 项
                </div>
              </div>
            </div>
          </div>
        </div>

        <!-- ---------- 周视图 ---------- -->
        <div v-else-if="view === 'week'" class="week-view">
          <div
            v-for="col in weekCells"
            :key="col.key"
            class="week-col"
            :class="{ today: col.isToday, selected: col.key === selectedKey }"
            @click="selectDay(col)"
            @dblclick="openCreate(col.key)"
          >
            <div class="week-col-head">
              <span class="week-col-weekday">{{ col.weekday }}</span>
              <span class="week-col-day">{{ col.day }}</span>
            </div>
            <div class="week-col-body">
              <div
                v-for="e in col.events"
                :key="e.id"
                class="week-event"
                :class="{ done: e.status === 'done', cancelled: e.status === 'cancelled' }"
                :style="chipStyle(e)"
              >
                <div class="week-event-time">{{ timeOf(e.event_date) }}</div>
                <div class="week-event-title">{{ e.title }}</div>
                <div v-if="e.case_no" class="week-event-case">{{ e.case_no }}</div>
              </div>
              <div v-if="!col.events.length" class="week-empty">—</div>
            </div>
          </div>
        </div>

        <!-- ---------- 日视图（时间轴） ---------- -->
        <div v-else class="day-view">
          <el-empty
            v-if="!selectedEvents.length"
            :description="`${selectedLabel} 暂无日程`"
            :image-size="90"
          >
            <el-button type="primary" plain size="small" @click="openCreate(selectedKey)">
              新建日程
            </el-button>
          </el-empty>

          <div v-for="e in selectedEvents" :key="e.id" class="agenda-row">
            <div class="agenda-time">
              <div class="t">{{ timeOf(e.event_date) || '全天' }}</div>
              <div class="w">{{ weekdayLabel(e.event_date) }}</div>
            </div>
            <div class="agenda-axis">
              <span class="axis-dot" :style="{ background: typeMeta(e.schedule_type).color }" />
            </div>
            <div
              class="agenda-card"
              :class="{ done: e.status === 'done', cancelled: e.status === 'cancelled' }"
            >
              <div class="agenda-head">
                <span class="type-pill" :style="chipStyle(e)">
                  {{ typeMeta(e.schedule_type).label }}
                </span>
                <span class="agenda-title">{{ e.title }}</span>
                <el-tag :type="statusMeta(e.status).type" size="small" effect="light">
                  {{ statusMeta(e.status).label }}
                </el-tag>
                <el-tag v-if="e.is_overdue" type="danger" size="small" effect="dark">已逾期</el-tag>
              </div>
              <div class="agenda-meta">
                <span>{{ fmtDateTime(e.event_date) }}</span>
                <span v-if="e.case_no">· {{ e.case_no }} {{ e.case_title || '' }}</span>
                <span v-if="e.client_name">· 客户 {{ e.client_name }}</span>
                <span v-if="e.lawyer_name">· 承办 {{ e.lawyer_name }}</span>
              </div>
              <div v-if="e.remark" class="agenda-remark">{{ e.remark }}</div>
              <div class="agenda-actions">
                <template v-if="canEdit(e)">
                  <el-button
                    v-if="e.status !== 'done'"
                    link
                    type="success"
                    size="small"
                    @click="markStatus(e, 'done')"
                  >
                    标记完成
                  </el-button>
                  <el-button v-else link size="small" @click="markStatus(e, 'pending')">
                    恢复待办
                  </el-button>
                  <el-button
                    v-if="e.status !== 'cancelled'"
                    link
                    type="info"
                    size="small"
                    @click="markStatus(e, 'cancelled')"
                  >
                    取消
                  </el-button>
                  <el-button link type="primary" size="small" @click="openEdit(e)">编辑</el-button>
                  <el-button link type="danger" size="small" @click="remove(e)">删除</el-button>
                </template>
                <span v-else class="readonly-hint">仅创建人可修改</span>
              </div>
            </div>
          </div>
        </div>
      </el-card>

      <!-- ---------- 右侧：选中日期清单 ---------- -->
      <el-card v-if="view !== 'day'" shadow="never" class="side-card">
        <template #header>
          <div class="card-head">
            <span>{{ selectedLabel }}</span>
            <el-tag size="small" effect="plain">{{ selectedEvents.length }} 项</el-tag>
          </div>
        </template>

        <el-empty v-if="!selectedEvents.length" description="当日暂无日程" :image-size="80">
          <el-button size="small" type="primary" plain @click="openCreate(selectedKey)">
            新建日程
          </el-button>
        </el-empty>

        <div v-else class="side-list">
          <div
            v-for="e in selectedEvents"
            :key="e.id"
            class="side-item"
            :class="{ done: e.status === 'done', cancelled: e.status === 'cancelled' }"
          >
            <div class="side-top">
              <span class="type-pill" :style="chipStyle(e)">{{ typeMeta(e.schedule_type).label }}</span>
              <span class="side-time">{{ timeOf(e.event_date) }}</span>
              <el-tag :type="statusMeta(e.status).type" size="small" effect="plain">
                {{ statusMeta(e.status).label }}
              </el-tag>
            </div>
            <div class="side-title">{{ e.title }}</div>
            <div v-if="e.case_no || e.client_name" class="side-meta">
              <span v-if="e.case_no">{{ e.case_no }}</span>
              <span v-if="e.client_name">{{ e.client_name }}</span>
            </div>
            <div v-if="e.remark" class="side-remark">{{ e.remark }}</div>
            <div v-if="canEdit(e)" class="side-actions">
              <el-button
                v-if="e.status !== 'done'"
                link
                type="success"
                size="small"
                @click="markStatus(e, 'done')"
              >
                完成
              </el-button>
              <el-button v-else link size="small" @click="markStatus(e, 'pending')">恢复</el-button>
              <el-button link type="primary" size="small" @click="openEdit(e)">编辑</el-button>
              <el-button link type="danger" size="small" @click="remove(e)">删除</el-button>
            </div>
            <div v-if="e.is_overdue" class="side-overdue">已逾期未办</div>
          </div>
        </div>
      </el-card>
    </div>

    <ScheduleForm
      v-model="formVisible"
      :schedule="editing"
      :default-date="defaultDate"
      @saved="onSaved"
    />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowLeft, ArrowRight, Plus } from '@element-plus/icons-vue'
import {
  deleteSchedule,
  getScheduleCalendar,
  getTodaySchedules,
  listSchedules,
  updateScheduleStatus,
} from '@/api/schedule'
import {
  SCHEDULE_TYPE_META,
  SCHEDULE_TYPE_OPTIONS,
  WEEKDAYS,
  addDays,
  dateKey,
  endOfMonth,
  fmtDateTime,
  fmtMonthDay,
  monthGridRange,
  startOfMonth,
  startOfWeek,
  statusMeta,
  timeOf,
  toDate,
  typeMeta,
  weekdayLabel,
} from '@/utils/schedule'
import { useUserStore } from '@/stores/user'
import ScheduleForm from './ScheduleForm.vue'

const route = useRoute()
const userStore = useUserStore()

// ---------- 视图状态 ----------
const view = ref('month')
const cursor = ref(toDate(new Date()))
const selectedKey = ref(dateKey(new Date()))
const typeFilter = ref('')
const loading = ref(false)
const dayMap = ref({})

const formVisible = ref(false)
const editing = ref(null)
const defaultDate = ref('')

const stats = ref({ month: 0, week: 0, today: 0, overdue: 0 })

// ---------- 区间计算 ----------
const viewRange = computed(() => {
  if (view.value === 'month') {
    const { start, end } = monthGridRange(cursor.value)
    return { start, end }
  }
  if (view.value === 'week') {
    const start = startOfWeek(cursor.value)
    return { start, end: addDays(start, 6) }
  }
  const start = toDate(cursor.value)
  return { start, end: start }
})

const periodLabel = computed(() => {
  const c = toDate(cursor.value)
  if (view.value === 'month') return `${c.getFullYear()} 年 ${c.getMonth() + 1} 月`
  if (view.value === 'week') {
    const start = startOfWeek(c)
    const end = addDays(start, 6)
    return `${fmtMonthDay(start)} - ${fmtMonthDay(end)}`
  }
  return `${c.getFullYear()} 年 ${c.getMonth() + 1} 月 ${c.getDate()} 日 ${weekdayLabel(c)}`
})

const viewTitle = computed(() =>
  view.value === 'month' ? '本月日程' : view.value === 'week' ? '本周日程' : '当日日程',
)

const selectedLabel = computed(() => {
  const d = toDate(selectedKey.value)
  if (!d) return '—'
  const isToday = selectedKey.value === dateKey(new Date())
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${weekdayLabel(d)}${isToday ? '（今天）' : ''}`
})

const statCards = computed(() => [
  {
    label: '本月日程',
    value: stats.value.month,
    icon: 'Calendar',
    bg: '#eef2fa',
    color: '#1d2b47',
  },
  {
    label: '本周日程',
    value: stats.value.week,
    icon: 'Clock',
    bg: '#faf3e7',
    color: '#a5813d',
  },
  {
    label: '今日待办',
    value: stats.value.today,
    icon: 'Bell',
    bg: '#eaf5ef',
    color: '#1D9E75',
  },
  {
    label: '逾期未办',
    value: stats.value.overdue,
    icon: 'WarningFilled',
    bg: '#faeef0',
    color: '#993556',
    danger: stats.value.overdue > 0,
  },
])

// ---------- 数据 ----------
function eventsOf(key) {
  const list = dayMap.value[key] || []
  if (!typeFilter.value) return list
  return list.filter((e) => e.schedule_type === typeFilter.value)
}

const monthCells = computed(() => {
  const start = viewRange.value.start
  const today = dateKey(new Date())
  const cells = []
  for (let i = 0; i < 42; i += 1) {
    const d = addDays(start, i)
    const key = dateKey(d)
    cells.push({
      key,
      day: d.getDate(),
      inMonth: d.getMonth() === cursor.value.getMonth(),
      isToday: key === today,
      weekend: d.getDay() === 0 || d.getDay() === 6,
      events: eventsOf(key),
    })
  }
  return cells
})

const weekCells = computed(() => {
  const start = startOfWeek(cursor.value)
  const today = dateKey(new Date())
  return Array.from({ length: 7 }, (_, i) => {
    const d = addDays(start, i)
    const key = dateKey(d)
    return {
      key,
      day: `${d.getMonth() + 1}/${d.getDate()}`,
      weekday: WEEKDAYS[i],
      isToday: key === today,
      events: eventsOf(key),
    }
  })
})

const selectedEvents = computed(() => {
  const list = eventsOf(selectedKey.value)
  return [...list].sort((a, b) => String(a.event_date).localeCompare(String(b.event_date)))
})

async function load() {
  loading.value = true
  try {
    const { start, end } = viewRange.value
    const data = await getScheduleCalendar({
      start: dateKey(start),
      end: dateKey(end),
    })
    const map = {}
    for (const day of data.days || []) {
      map[dateKey(day.date)] = day.items || []
    }
    dayMap.value = map
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  const today = new Date()
  const mStart = startOfMonth(today)
  const mEnd = endOfMonth(today)
  const wStart = startOfWeek(today)
  const wEnd = addDays(wStart, 6)

  try {
    const [monthRes, weekRes, todayList, overdueRes] = await Promise.all([
      listSchedules({ start: dateKey(mStart), end: dateKey(mEnd), page: 1, page_size: 1 }),
      listSchedules({ start: dateKey(wStart), end: dateKey(wEnd), page: 1, page_size: 1 }),
      getTodaySchedules(),
      listSchedules({
        status: 'pending',
        end: dateKey(today),
        page: 1,
        page_size: 100,
      }),
    ])
    stats.value = {
      month: monthRes.total || 0,
      week: weekRes.total || 0,
      today: (todayList || []).filter((x) => x.status === 'pending').length,
      overdue: (overdueRes.items || []).filter((x) => x.is_overdue).length,
    }
  } catch {
    /* 概览拉取失败不影响日历本身 */
  }
}

function refreshAll() {
  load()
  loadStats()
}

// ---------- 交互 ----------
function shift(step) {
  const c = toDate(cursor.value)
  if (view.value === 'month') {
    cursor.value = new Date(c.getFullYear(), c.getMonth() + step, 1)
  } else if (view.value === 'week') {
    cursor.value = addDays(c, step * 7)
  } else {
    cursor.value = addDays(c, step)
  }

  // 选中日期落到新区间外时跟随到当期首日，避免右侧清单显示上一屏的数据
  const { start, end } = viewRange.value
  const key = selectedKey.value
  if (key < dateKey(start) || key > dateKey(end)) {
    const target =
      view.value === 'month'
        ? new Date(cursor.value.getFullYear(), cursor.value.getMonth(), 1)
        : start
    selectedKey.value = dateKey(target)
  }
  load()
}

function goToday() {
  cursor.value = toDate(new Date())
  selectedKey.value = dateKey(new Date())
  load()
}

function onViewChange() {
  const c = toDate(selectedKey.value) || toDate(new Date())
  if (view.value !== 'month') cursor.value = c
  load()
}

function selectDay(cell) {
  selectedKey.value = cell.key
  if (cell.inMonth === false) {
    cursor.value = toDate(cell.key)
    load()
  } else if (view.value === 'day') {
    cursor.value = toDate(cell.key)
    load()
  }
}

function chipStyle(e) {
  const meta = typeMeta(e.schedule_type)
  return {
    background: meta.bg,
    color: meta.color,
    borderLeftColor: meta.color,
  }
}

function canEdit(e) {
  return userStore.role === 'admin' || e.user_id === userStore.userInfo?.id
}

function openCreate(key) {
  editing.value = null
  defaultDate.value = key || selectedKey.value
  formVisible.value = true
}

function openEdit(row) {
  editing.value = row
  defaultDate.value = ''
  formVisible.value = true
}

function onSaved() {
  formVisible.value = false
  refreshAll()
}

async function markStatus(row, status) {
  await updateScheduleStatus(row.id, status)
  ElMessage.success(status === 'done' ? '已标记完成' : status === 'cancelled' ? '日程已取消' : '已恢复待办')
  refreshAll()
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确定删除日程「${row.title}」吗？`, '删除日程', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteSchedule(row.id)
  ElMessage.success('日程已删除')
  refreshAll()
}

// ---------- 初始化 ----------
onMounted(() => {
  const qDate = route.query.date
  if (qDate && toDate(qDate)) {
    cursor.value = toDate(qDate)
    selectedKey.value = dateKey(qDate)
  }
  const qView = route.query.view
  if (['month', 'week', 'day'].includes(qView)) view.value = qView
  refreshAll()
})
</script>

<style scoped>
.schedule-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 概览卡 ---------- */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.2;
}

.stat-value.danger {
  color: var(--el-color-danger);
}

.stat-label {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 4px;
}

/* ---------- 工具条 ---------- */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.period-nav {
  display: flex;
  align-items: center;
  gap: 4px;
}

.nav-btn {
  color: var(--brand-muted);
}

.nav-btn:hover {
  color: var(--brand-gold-deep);
}

.period-text {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
  min-width: 150px;
  text-align: center;
  letter-spacing: 0.5px;
}

.today-btn {
  margin-left: 8px;
}

.type-sel {
  width: 132px;
}

.spacer {
  flex: 1;
}

/* ---------- 主体 ---------- */
.body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 330px;
  gap: 16px;
  align-items: start;
}

.body.wide {
  grid-template-columns: minmax(0, 1fr);
}

.cal-card,
.side-card {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  font-weight: 600;
  color: var(--brand-ink);
  font-size: 14px;
}

.legend {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}

.legend-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  display: inline-block;
}

/* ---------- 月视图 ---------- */
.weekday-row {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  border-bottom: 1px solid var(--brand-line);
  padding-bottom: 8px;
  margin-bottom: 8px;
}

.weekday {
  text-align: center;
  font-size: 12px;
  color: var(--brand-muted);
  letter-spacing: 1px;
}

.month-grid {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 6px;
}

.day-cell {
  min-height: 104px;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 6px 6px 4px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  overflow: hidden;
}

.day-cell:hover {
  background: #f7f8fb;
}

.day-cell.other .day-num {
  color: #c3c8d4;
}

.day-cell.other {
  background: #fbfbfd;
}

.day-cell.today {
  background: #fdf9f0;
  border-color: rgba(201, 165, 92, 0.55);
}

.day-cell.selected {
  border-color: var(--brand-navy);
  box-shadow: 0 0 0 2px rgba(29, 43, 71, 0.08);
}

.day-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.day-num {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
}

.day-cell.weekend .day-num {
  color: #993556;
}

.day-cell.other.weekend .day-num {
  color: #d9c0c8;
}

.day-count {
  font-size: 11px;
  color: var(--brand-muted);
  background: #eef0f5;
  border-radius: 8px;
  padding: 0 5px;
  line-height: 16px;
}

.day-events {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.event-chip {
  display: flex;
  align-items: center;
  gap: 4px;
  border-left: 2px solid transparent;
  border-radius: 4px;
  padding: 2px 4px;
  font-size: 11px;
  line-height: 1.5;
  overflow: hidden;
}

.event-chip.done {
  opacity: 0.65;
}

.event-chip.done .chip-title {
  text-decoration: line-through;
}

.event-chip.cancelled {
  opacity: 0.45;
  text-decoration: line-through;
}

.chip-time {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
  opacity: 0.85;
}

.chip-title {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.more-text {
  font-size: 11px;
  color: var(--brand-muted);
  padding-left: 4px;
}

/* ---------- 周视图 ---------- */
.week-view {
  display: grid;
  grid-template-columns: repeat(7, 1fr);
  gap: 8px;
}

.week-col {
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  min-height: 420px;
  cursor: pointer;
  overflow: hidden;
  background: #fff;
  transition: border-color 0.15s, box-shadow 0.15s;
}

.week-col:hover {
  border-color: #cfd4e0;
}

.week-col.today {
  border-color: rgba(201, 165, 92, 0.6);
  background: #fdf9f0;
}

.week-col.selected {
  border-color: var(--brand-navy);
  box-shadow: 0 0 0 2px rgba(29, 43, 71, 0.08);
}

.week-col-head {
  padding: 8px 6px;
  text-align: center;
  border-bottom: 1px solid var(--brand-line);
  background: #fafbfd;
}

.week-col.today .week-col-head {
  background: rgba(201, 165, 92, 0.12);
}

.week-col-weekday {
  display: block;
  font-size: 12px;
  color: var(--brand-muted);
}

.week-col-day {
  display: block;
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-top: 2px;
}

.week-col-body {
  padding: 6px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.week-event {
  border-left: 3px solid transparent;
  border-radius: 6px;
  padding: 5px 6px;
  font-size: 12px;
}

.week-event.done {
  opacity: 0.6;
}

.week-event.cancelled {
  opacity: 0.45;
  text-decoration: line-through;
}

.week-event-time {
  font-size: 11px;
  opacity: 0.8;
  font-variant-numeric: tabular-nums;
}

.week-event-title {
  margin-top: 2px;
  line-height: 1.45;
  word-break: break-all;
}

.week-event-case {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.7;
}

.week-empty {
  color: #d3d7e0;
  text-align: center;
  font-size: 12px;
  padding-top: 10px;
}

/* ---------- 日视图 ---------- */
.day-view {
  padding: 4px 4px 8px;
}

.agenda-row {
  display: grid;
  grid-template-columns: 68px 24px minmax(0, 1fr);
  gap: 8px;
}

.agenda-time {
  text-align: right;
  padding-top: 14px;
}

.agenda-time .t {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
}

.agenda-time .w {
  font-size: 11px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.agenda-axis {
  position: relative;
  display: flex;
  justify-content: center;
}

.agenda-axis::before {
  content: '';
  position: absolute;
  top: 0;
  bottom: 0;
  width: 1px;
  background: var(--brand-line);
}

.axis-dot {
  position: relative;
  margin-top: 20px;
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 2px solid #fff;
  box-shadow: 0 0 0 1px rgba(29, 43, 71, 0.12);
}

.agenda-card {
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 12px 14px;
  margin-bottom: 12px;
  background: #fff;
}

.agenda-card.done {
  background: #fafbfd;
}

.agenda-card.cancelled {
  opacity: 0.6;
}

.agenda-head {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.type-pill {
  border-left: 2px solid transparent;
  border-radius: 4px;
  padding: 1px 7px;
  font-size: 12px;
  line-height: 18px;
  flex-shrink: 0;
}

.agenda-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.agenda-meta {
  margin-top: 8px;
  font-size: 12px;
  color: var(--brand-muted);
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.agenda-remark {
  margin-top: 8px;
  font-size: 13px;
  color: var(--brand-text);
  background: #f7f8fb;
  border-radius: 6px;
  padding: 8px 10px;
  line-height: 1.7;
  white-space: pre-wrap;
}

.agenda-actions {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.readonly-hint {
  font-size: 12px;
  color: var(--brand-muted);
}

/* ---------- 右侧清单 ---------- */
.side-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 560px;
  overflow-y: auto;
}

.side-item {
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 10px 12px;
}

.side-item.done {
  background: #fafbfd;
}

.side-item.cancelled {
  opacity: 0.6;
}

.side-top {
  display: flex;
  align-items: center;
  gap: 8px;
}

.side-time {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
}

.side-title {
  margin-top: 6px;
  font-size: 13px;
  font-weight: 500;
  color: var(--brand-ink);
  line-height: 1.5;
  word-break: break-all;
}

.side-meta {
  margin-top: 4px;
  display: flex;
  gap: 8px;
  font-size: 12px;
  color: var(--brand-muted);
}

.side-remark {
  margin-top: 6px;
  font-size: 12px;
  color: var(--brand-text);
  line-height: 1.6;
  background: #f7f8fb;
  border-radius: 6px;
  padding: 6px 8px;
}

.side-actions {
  margin-top: 6px;
  display: flex;
  gap: 2px;
}

.side-overdue {
  margin-top: 6px;
  font-size: 12px;
  color: var(--el-color-danger);
}

/* ============================================================
   手机端（≤768px）
   月历 / 周历都是 7 列布局，窄屏必须换一种表达方式：
   月视图保留七列但把事件压成色条，周视图改为横向滑动的列。
   ============================================================ */
@media (max-width: 768px) {
  /* 右栏固定 330px，在 375px 屏幕上会把日历列挤成 0 宽，改为上下堆叠 */
  .body,
  .body.wide {
    grid-template-columns: minmax(0, 1fr);
    gap: 12px;
  }

  /* ---------- 统计卡：四张卡两列正好，三等分会把第四张挤到单独一行 ---------- */
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
    gap: 8px;
  }

  .stat-card {
    flex-direction: column;
    align-items: flex-start;
    gap: 6px;
    padding: 10px 10px 12px;
    border-radius: 10px;
  }

  .stat-icon {
    width: 30px;
    height: 30px;
    border-radius: 8px;
  }

  .stat-value {
    font-size: 17px;
  }

  .stat-label {
    font-size: 11px;
    margin-top: 2px;
    white-space: nowrap;
  }

  /* ---------- 工具条 ---------- */
  .toolbar {
    gap: 8px;
  }

  .period-text {
    min-width: 0;
    font-size: 14px;
    letter-spacing: 0;
  }

  /* ---------- 月视图：格子压到 64px，事件只留色条 ---------- */
  .weekday {
    font-size: 11px;
    letter-spacing: 0;
  }

  .month-grid {
    gap: 2px;
  }

  .day-cell {
    min-height: 64px;
    padding: 3px 2px;
    border-radius: 6px;
  }

  .day-num {
    font-size: 12px;
  }

  .day-events {
    gap: 2px;
  }

  /* 46px 宽的格子里塞不下"09:30 开庭"，压成一条色带，点进日视图看详情 */
  .event-chip {
    height: 5px;
    padding: 0;
    border-left-width: 0;
    border-radius: 2px;
    filter: saturate(2.2);
  }

  .chip-time,
  .chip-title {
    display: none;
  }

  .more-text {
    font-size: 10px;
    padding-left: 0;
    text-align: right;
  }

  /* ---------- 周视图：七列并排挤不下，改成横向滑动 ---------- */
  .week-view {
    display: flex;
    gap: 8px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
    padding-bottom: 6px;
  }

  .week-col {
    flex: 0 0 132px;
    min-height: 300px;
  }
}
</style>
