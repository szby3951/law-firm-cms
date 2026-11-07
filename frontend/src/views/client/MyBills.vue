<template>
  <div class="my-bills">
    <!-- 汇总 -->
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

    <el-alert
      v-if="overdueCount > 0"
      type="error"
      :closable="false"
      show-icon
      class="overdue-alert"
    >
      <template #title>
        您有 {{ overdueCount }} 期账单已逾期，未缴金额 ¥{{ money(overdueAmount) }}，可在线缴费或联系承办律师
      </template>
    </el-alert>

    <!-- 账单列表 -->
    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="card-head">
          <span>我的账单</span>
          <el-radio-group v-model="filter" size="small">
            <el-radio-button value="all">全部（{{ bills.length }}）</el-radio-button>
            <el-radio-button value="unpaid">待缴（{{ unpaidBills.length }}）</el-radio-button>
            <el-radio-button value="paid">已缴（{{ paidBills.length }}）</el-radio-button>
          </el-radio-group>
        </div>
      </template>

      <el-table
        :data="filteredBills"
        v-loading="loading"
        stripe
        class="bill-table"
        style="width: 100%"
      >
        <el-table-column label="案件" min-width="128" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="case-cell">
              <span class="case-title">{{ row.case_title || `案件 #${row.case_id}` }}</span>
              <span class="case-no">{{ row.case_no || '—' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="期次" width="62" align="center">
          <template #default="{ row }">第 {{ row.period_no }} 期</template>
        </el-table-column>

        <el-table-column label="应收金额" width="104" align="right">
          <template #default="{ row }">¥{{ money(row.due_amount) }}</template>
        </el-table-column>

        <el-table-column label="已缴金额" width="104" align="right">
          <template #default="{ row }">
            <span class="paid">¥{{ money(row.paid_amount) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="待缴金额" width="104" align="right">
          <template #default="{ row }">
            <span :class="{ unpaid: num(row.unpaid_amount) > 0 }">
              ¥{{ money(row.unpaid_amount) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="应收日期" width="88">
          <template #default="{ row }">{{ formatDate(row.due_date) }}</template>
        </el-table-column>

        <el-table-column label="状态" width="86" align="center">
          <template #default="{ row }">
            <div class="status-cell">
              <el-tag :type="periodStatusMeta(row).type" effect="light" size="small">
                {{ periodStatusMeta(row).label }}
              </el-tag>
              <span v-if="row.status !== 'paid' && row.overdue_days > 0" class="overdue-days">
                逾期 {{ row.overdue_days }} 天
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="发票" width="78">
          <template #default="{ row }">
            <div class="invoice-cell">
              <el-tag
                :type="INVOICE_STATUS_META[row.invoice_status]?.type || 'info'"
                effect="plain"
                size="small"
              >
                {{ INVOICE_STATUS_META[row.invoice_status]?.label || '未开票' }}
              </el-tag>
              <span v-if="row.invoice_no" class="invoice-no">{{ row.invoice_no }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="缴费时间" width="104">
          <template #default="{ row }">
            <div v-if="row.paid_at" class="pay-time-cell">
              <span class="pay-date">{{ formatDate(row.paid_at) }}</span>
              <span class="pay-clock">
                {{ formatClock(row.paid_at) }}
                <span v-if="row.last_pay_source === 'online'" class="online-badge">
                  在线支付
                </span>
              </span>
            </div>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="62" align="center" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.status !== 'paid'" link type="primary" @click="openPay(row)">
              去缴费
            </el-button>
            <span v-else class="paid-done">已完成</span>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !filteredBills.length" description="暂无账单" :image-size="100" />
    </el-card>

    <!-- 在线缴费收银台（沙箱） -->
    <PaymentCheckout v-model="payVisible" :bill="payBill" @paid="load" />
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { listMyBills } from '@/api/billing'
import {
  INVOICE_STATUS_META,
  formatDate,
  money,
  num,
  periodStatusMeta,
} from '@/utils/billing'

// 只取时分，日期另起一行展示，避免缴费时间过宽被挤出可视区
function formatClock(s) {
  if (!s) return ''
  return String(s).replace('T', ' ').slice(11, 16)
}
import PaymentCheckout from './PaymentCheckout.vue'

const loading = ref(false)
const bills = ref([])
const filter = ref('all')

const unpaidBills = computed(() => bills.value.filter((b) => b.status !== 'paid'))
const paidBills = computed(() => bills.value.filter((b) => b.status === 'paid'))

const filteredBills = computed(() => {
  if (filter.value === 'unpaid') return unpaidBills.value
  if (filter.value === 'paid') return paidBills.value
  return bills.value
})

const totalDue = computed(() => bills.value.reduce((s, b) => s + num(b.due_amount), 0))
const totalPaid = computed(() => bills.value.reduce((s, b) => s + num(b.paid_amount), 0))
const totalUnpaid = computed(() => bills.value.reduce((s, b) => s + num(b.unpaid_amount), 0))

const overdueBills = computed(() =>
  bills.value.filter((b) => b.status !== 'paid' && num(b.overdue_days) > 0),
)
const overdueCount = computed(() => overdueBills.value.length)
const overdueAmount = computed(() =>
  overdueBills.value.reduce((s, b) => s + num(b.unpaid_amount), 0),
)

const statCards = computed(() => [
  {
    label: '应收合计',
    value: `¥${money(totalDue.value)}`,
    icon: 'Tickets',
    bg: '#eef2fa',
    color: '#1d2b47',
  },
  {
    label: '已缴合计',
    value: `¥${money(totalPaid.value)}`,
    icon: 'CircleCheck',
    bg: '#eaf5ef',
    color: '#1D9E75',
  },
  {
    label: '待缴合计',
    value: `¥${money(totalUnpaid.value)}`,
    icon: 'Wallet',
    bg: '#faf3e7',
    color: '#a5813d',
    danger: totalUnpaid.value > 0,
  },
  {
    label: '逾期未缴',
    value: `¥${money(overdueAmount.value)}`,
    icon: 'WarningFilled',
    bg: '#faeef0',
    color: '#993556',
    danger: overdueAmount.value > 0,
  },
])

async function load() {
  loading.value = true
  try {
    bills.value = await listMyBills()
  } finally {
    loading.value = false
  }
}

const payVisible = ref(false)
const payBill = ref(null)

function openPay(bill) {
  payBill.value = bill
  payVisible.value = true
}

onMounted(load)
</script>

<style scoped>
.my-bills {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

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

.overdue-alert {
  border-radius: 10px;
}

.table-card {
  border-radius: 12px;
}

/* 压缩单元格左右留白，为金额与时间列腾出空间，避免横向滚动 */
.bill-table {
  font-size: 13px;
}

.bill-table :deep(.el-table__cell) {
  padding: 9px 0;
}

.bill-table :deep(.cell) {
  padding: 0 6px;
  line-height: 1.4;
}

.bill-table :deep(.el-table__header .cell) {
  color: var(--brand-muted);
  font-weight: 500;
}

.bill-table :deep(.el-table__cell.is-right .cell) {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.case-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.case-title {
  color: var(--brand-text);
}

.case-no {
  font-size: 12px;
  color: var(--brand-muted);
}

.paid {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.unpaid {
  color: var(--el-color-danger);
  font-weight: 600;
}

.status-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.overdue-days {
  font-size: 12px;
  color: var(--el-color-danger);
}

.invoice-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 2px;
}

.invoice-no {
  font-size: 11px;
  color: var(--brand-muted);
  line-height: 1.2;
}

.pay-time-cell {
  display: flex;
  flex-direction: column;
  gap: 1px;
  line-height: 1.3;
}

.pay-date {
  font-size: 13px;
  color: var(--brand-text);
}

.pay-clock {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: var(--brand-muted);
}

.online-badge {
  font-size: 10px;
  line-height: 1.5;
  color: #1d9e75;
  background: #eaf5ef;
  border-radius: 3px;
  padding: 0 3px;
  white-space: nowrap;
}

.muted {
  color: var(--brand-muted);
}

.paid-done {
  font-size: 12px;
  color: var(--brand-muted);
}
</style>
