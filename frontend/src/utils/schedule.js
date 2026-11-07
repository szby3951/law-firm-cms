// 日程与通知模块共用的枚举元数据、日期工具

// ---------- 枚举 ----------

export const WEEKDAYS = ['周一', '周二', '周三', '周四', '周五', '周六', '周日']

// 日程类型：颜色沿用品牌色系（酒红/哑金/墨绿/墨蓝）
export const SCHEDULE_TYPE_META = {
  hearing: { label: '开庭', color: '#993556', bg: '#faeef0', tag: 'danger', icon: 'Briefcase' },
  deadline: { label: '期限', color: '#a5813d', bg: '#faf3e7', tag: 'warning', icon: 'Timer' },
  visit: { label: '回访', color: '#1D9E75', bg: '#eaf5ef', tag: 'success', icon: 'Phone' },
  meeting: { label: '会议', color: '#1d2b47', bg: '#eef2fa', tag: 'primary', icon: 'ChatLineSquare' },
}

export const SCHEDULE_TYPE_OPTIONS = Object.entries(SCHEDULE_TYPE_META).map(
  ([value, m]) => ({ value, label: m.label }),
)

export const SCHEDULE_STATUS_META = {
  pending: { label: '待办', type: 'warning' },
  done: { label: '已完成', type: 'success' },
  cancelled: { label: '已取消', type: 'info' },
}

// 通知类型
export const NOTIFICATION_TYPE_META = {
  hearing: { label: '开庭提醒', color: '#993556', bg: '#faeef0', tag: 'danger', icon: 'Briefcase' },
  deadline: { label: '期限提醒', color: '#a5813d', bg: '#faf3e7', tag: 'warning', icon: 'Timer' },
  payment: { label: '缴费提醒', color: '#1D9E75', bg: '#eaf5ef', tag: 'success', icon: 'Money' },
  follow: { label: '跟进提醒', color: '#1d2b47', bg: '#eef2fa', tag: 'primary', icon: 'User' },
  contract: { label: '合同预警', color: '#6b5b95', bg: '#f1eef8', tag: 'info', icon: 'Tickets' },
  meeting: { label: '会议提醒', color: '#4a6fa5', bg: '#eef2fa', tag: 'primary', icon: 'ChatLineSquare' },
  system: { label: '系统通知', color: '#8a93a6', bg: '#f4f5f8', tag: 'info', icon: 'Bell' },
}

export function typeMeta(type) {
  return (
    SCHEDULE_TYPE_META[type] || {
      label: type,
      color: '#8a93a6',
      bg: '#f4f5f8',
      tag: 'info',
    }
  )
}

export function noticeMeta(type) {
  return (
    NOTIFICATION_TYPE_META[type] || {
      label: type,
      color: '#8a93a6',
      bg: '#f4f5f8',
      tag: 'info',
      icon: 'Bell',
    }
  )
}

export function statusMeta(status) {
  return SCHEDULE_STATUS_META[status] || { label: status, type: 'info' }
}

// ---------- 日期工具 ----------

const pad2 = (n) => String(n).padStart(2, '0')

// 任意日期值 → 当天 0 点 Date（支持 Date / 2026-11-04 / 2026-11-04T16:05:00）
export function toDate(value) {
  if (!value) return null
  if (value instanceof Date) {
    return new Date(value.getFullYear(), value.getMonth(), value.getDate())
  }
  const m = String(value).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/)
  if (!m) return null
  return new Date(Number(m[1]), Number(m[2]) - 1, Number(m[3]))
}

// 日期键：YYYY-MM-DD（日历分组用）
export function dateKey(value) {
  const d = toDate(value)
  if (!d) return ''
  return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`
}

// 时刻：HH:mm
export function timeOf(value) {
  if (!value) return ''
  const m = String(value).match(/[T ](\d{2}):(\d{2})/)
  return m ? `${m[1]}:${m[2]}` : ''
}

export function fmtDate(value) {
  return dateKey(value) || '—'
}

export function fmtDateTime(value) {
  if (!value) return '—'
  const d = dateKey(value)
  const t = timeOf(value)
  return t ? `${d} ${t}` : d
}

// 11月4日
export function fmtMonthDay(value) {
  const d = toDate(value)
  return d ? `${d.getMonth() + 1}月${d.getDate()}日` : '—'
}

// 周三
export function weekdayLabel(value) {
  const d = toDate(value)
  if (!d) return ''
  return WEEKDAYS[(d.getDay() + 6) % 7]
}

export function addDays(value, n) {
  const d = toDate(value) || toDate(new Date())
  return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n)
}

// 周起始（周一）
export function startOfWeek(value) {
  const d = toDate(value) || toDate(new Date())
  const offset = (d.getDay() + 6) % 7
  return addDays(d, -offset)
}

export function startOfMonth(value) {
  const d = toDate(value) || toDate(new Date())
  return new Date(d.getFullYear(), d.getMonth(), 1)
}

export function endOfMonth(value) {
  const d = toDate(value) || toDate(new Date())
  return new Date(d.getFullYear(), d.getMonth() + 1, 0)
}

export function isSameDay(a, b) {
  const x = dateKey(a)
  const y = dateKey(b)
  return !!x && x === y
}

// 月视图网格：6 行 × 7 列，覆盖当月并补齐首尾整周
export function monthGridRange(cursor) {
  const first = startOfMonth(cursor)
  const start = startOfWeek(first)
  return { start, end: addDays(start, 41) }
}

// 相对时间：刚刚 / N 分钟前 / 今天 16:05 / 昨天 09:00 / 11月2日
export function relativeTime(value) {
  if (!value) return '—'
  const iso = String(value).replace(' ', 'T')
  const ts = new Date(iso).getTime()
  if (!Number.isFinite(ts)) return fmtDateTime(value)

  const now = Date.now()
  const diff = now - ts
  if (diff >= 0 && diff < 60 * 1000) return '刚刚'
  if (diff >= 0 && diff < 60 * 60 * 1000) return `${Math.floor(diff / 60000)} 分钟前`

  const today = new Date()
  if (isSameDay(value, today)) return `今天 ${timeOf(value)}`
  if (isSameDay(value, addDays(today, -1))) return `昨天 ${timeOf(value)}`

  const d = toDate(value)
  if (d && d.getFullYear() === today.getFullYear()) {
    return `${d.getMonth() + 1}月${d.getDate()}日`
  }
  return fmtDate(value)
}
