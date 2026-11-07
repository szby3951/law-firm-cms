<template>
  <div class="collect-list">
    <div class="back-bar">
      <el-button link @click="back">
        <el-icon><ArrowLeft /></el-icon>返回收费列表
      </el-button>
    </div>

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

    <!-- 筛选 -->
    <div class="filter-bar">
      <span class="filter-label">逾期范围</span>
      <el-radio-group v-model="minOverdueDays" @change="load">
        <el-radio-button :value="0">全部到期未结清</el-radio-button>
        <el-radio-button :value="1">已逾期</el-radio-button>
        <el-radio-button :value="30">逾期 30 天以上</el-radio-button>
        <el-radio-button :value="90">逾期 90 天以上</el-radio-button>
      </el-radio-group>

      <div class="spacer" />

      <el-button :loading="loading" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </div>

    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="card-head">
          <span>催收清单</span>
          <span class="sub">已到期且未结清的期次，按应收日期升序</span>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="案件" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="case-cell">
              <el-link type="primary" :underline="false" @click="goPlan(row.fee_plan_id)">
                {{ row.case_title || `案件 #${row.case_id}` }}
              </el-link>
              <span class="case-no">{{ row.case_no || '—' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="client_name" label="委托客户" width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.client_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="期次" width="80" align="center">
          <template #default="{ row }">第 {{ row.period_no }} 期</template>
        </el-table-column>

        <el-table-column label="应收金额" width="120" align="right">
          <template #default="{ row }">¥{{ money(row.due_amount) }}</template>
        </el-table-column>

        <el-table-column label="已收金额" width="120" align="right">
          <template #default="{ row }">¥{{ money(row.paid_amount) }}</template>
        </el-table-column>

        <el-table-column label="未收金额" width="120" align="right">
          <template #default="{ row }">
            <span class="unpaid">¥{{ money(row.unpaid_amount) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="应收日期" width="110">
          <template #default="{ row }">{{ formatDate(row.due_date) }}</template>
        </el-table-column>

        <el-table-column label="逾期天数" width="140" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.overdue_days > 0" type="danger" effect="light" size="small">
              逾期 {{ row.overdue_days }} 天
            </el-tag>
            <el-tag v-else type="warning" effect="light" size="small">今日到期</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="150" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openPayment(row)">登记收款</el-button>
            <el-button link type="primary" @click="goPlan(row.fee_plan_id)">查看方案</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !rows.length"
        :description="minOverdueDays > 0 ? '该逾期范围内暂无催收任务' : '暂无到期未结清的账单'"
        :image-size="100"
      />
    </el-card>

    <PaymentDialog v-model="paymentVisible" :period="currentPeriod" @saved="onPaid" />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowLeft, Refresh } from '@element-plus/icons-vue'
import { listCollectList } from '@/api/billing'
import { formatDate, money, num } from '@/utils/billing'
import PaymentDialog from './PaymentDialog.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const rows = ref([])
const minOverdueDays = ref(0)

const paymentVisible = ref(false)
const currentPeriod = ref(null)

const totalUnpaid = computed(() => rows.value.reduce((s, r) => s + num(r.unpaid_amount), 0))
const clientCount = computed(() => new Set(rows.value.map((r) => r.client_id)).size)
const maxOverdue = computed(() =>
  rows.value.reduce((m, r) => Math.max(m, num(r.overdue_days)), 0),
)

const statCards = computed(() => [
  {
    label: '待催收期次',
    value: `${rows.value.length} 期`,
    icon: 'Bell',
    bg: '#faeef0',
    color: '#993556',
  },
  {
    label: '待收金额合计',
    value: `¥${money(totalUnpaid.value)}`,
    icon: 'Money',
    bg: '#faf3e7',
    color: '#a5813d',
    danger: totalUnpaid.value > 0,
  },
  {
    label: '涉及客户',
    value: `${clientCount.value} 位`,
    icon: 'User',
    bg: '#eef2fa',
    color: '#1d2b47',
  },
  {
    label: '最长逾期',
    value: `${maxOverdue.value} 天`,
    icon: 'Timer',
    bg: '#eaf5ef',
    color: '#1D9E75',
  },
])

async function load() {
  loading.value = true
  try {
    rows.value = await listCollectList({ min_overdue_days: minOverdueDays.value })
  } finally {
    loading.value = false
  }
}

function openPayment(row) {
  currentPeriod.value = {
    id: row.period_id,
    period_no: row.period_no,
    due_amount: row.due_amount,
    paid_amount: row.paid_amount,
    unpaid_amount: row.unpaid_amount,
    due_date: row.due_date,
  }
  paymentVisible.value = true
}

function onPaid() {
  load()
}

function base() {
  return route.path.startsWith('/admin') ? '/admin' : '/lawyer'
}

function back() {
  router.push(`${base()}/billing`)
}

function goPlan(id) {
  router.push(`${base()}/billing/${id}`)
}

load()
</script>

<style scoped>
.collect-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.back-bar {
  margin-bottom: -4px;
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

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-label {
  font-size: 13px;
  color: var(--brand-muted);
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.card-head .sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.case-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.case-no {
  font-size: 12px;
  color: var(--brand-muted);
}

.unpaid {
  color: var(--el-color-danger);
  font-weight: 600;
}

/* ---------- 手机端：筛选栏竖排占满整行，避免输入框被压成一条 ---------- */
@media (max-width: 768px) {
  .filter-bar {
    gap: 8px;
  }

  .filter-bar .kw,
  .filter-bar .sel,
  .filter-bar .el-select,
  .filter-bar .el-date-editor,
  .filter-bar .client-filter {
    width: 100% !important;
    max-width: none;
  }

  .spacer {
    display: none;
  }
}
</style>
