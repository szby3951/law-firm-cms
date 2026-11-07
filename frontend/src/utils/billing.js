// 收费模块共用的枚举元数据与格式化工具

// 收费方式
export const FEE_TYPE_META = {
  fixed: { label: '固定收费', type: 'primary' },
  ratio: { label: '比例收费', type: 'success' },
  risk: { label: '风险代理', type: 'warning' },
  hourly: { label: '计时收费', type: 'info' },
}

// 期次收款状态
export const PERIOD_STATUS_META = {
  unpaid: { label: '未收款', type: 'info' },
  partial: { label: '部分收款', type: 'warning' },
  paid: { label: '已结清', type: 'success' },
}

// 发票状态
export const INVOICE_STATUS_META = {
  none: { label: '未开票', type: 'info' },
  applied: { label: '申请中', type: 'warning' },
  issued: { label: '已开票', type: 'success' },
}

// 常用收款方式（后端为自由文本，可直接落库）
export const PAY_METHODS = ['银行转账', '现金', '微信', '支付宝', '支票', '其他']

// 收款来源：线下登记 / 客户在线支付
export const PAY_SOURCE_META = {
  offline: { label: '线下登记', type: 'info' },
  online: { label: '在线支付', type: 'success' },
}

// 在线支付渠道（沙箱）
export const PAY_CHANNEL_META = {
  wechat: { label: '微信支付', icon: 'ChatDotRound', color: '#07c160' },
  alipay: { label: '支付宝', icon: 'Money', color: '#1677ff' },
  bank: { label: '银行卡', icon: 'CreditCard', color: '#1d2b47' },
}

// 支付订单状态
export const ORDER_STATUS_META = {
  pending: { label: '待支付', type: 'warning' },
  paid: { label: '已支付', type: 'success' },
  failed: { label: '支付失败', type: 'danger' },
  cancelled: { label: '已取消', type: 'info' },
  expired: { label: '已过期', type: 'info' },
}

// 金额格式化：12345.6 → 12,345.60；空值 → 0.00
export function money(value) {
  const n = Number(value ?? 0)
  if (!Number.isFinite(n)) return '0.00'
  return n.toLocaleString('zh-CN', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })
}

// 纯数字金额（用于进度计算等）
export function num(value) {
  const n = Number(value ?? 0)
  return Number.isFinite(n) ? n : 0
}

export function formatDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 10)
}

export function formatTime(s) {
  if (!s) return '—'
  return String(s).replace('T', ' ').slice(0, 16)
}

// 期次状态：未结清且已过应收日期时展示为逾期
export function periodStatusMeta(period) {
  if (!period) return { label: '—', type: 'info' }
  if (period.status !== 'paid' && num(period.overdue_days) > 0) {
    return { label: '逾期未结清', type: 'danger' }
  }
  return PERIOD_STATUS_META[period.status] || { label: period.status, type: 'info' }
}

// 方案整体收款状态：按已收/应收比例派生
export function planStatusMeta(plan) {
  const due = num(plan?.due_total ?? plan?.total_amount)
  const paid = num(plan?.paid_total)
  if (due > 0 && paid >= due - 0.005) return { key: 'paid', ...PERIOD_STATUS_META.paid }
  if (paid > 0) return { key: 'partial', ...PERIOD_STATUS_META.partial }
  return { key: 'unpaid', ...PERIOD_STATUS_META.unpaid }
}

// 回款百分比（0~100 整数，避免进度条超过 100）
export function progressPercent(due, paid) {
  const d = num(due)
  const p = num(paid)
  if (d <= 0) return 0
  return Math.min(100, Math.round((p / d) * 100))
}
