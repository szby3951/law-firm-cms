<template>
  <div class="billing-list">
    <!-- 营收概览 -->
    <div class="stat-block">
      <div class="stat-caption">
        <span class="caption-title">营收概览</span>
        <div class="caption-actions">
          <el-date-picker
            v-model="statsMonth"
            type="month"
            value-format="YYYY-MM"
            placeholder="统计月份"
            :clearable="false"
            size="small"
            class="month-pick"
            @change="loadStats"
          />
        </div>
      </div>

      <div class="stat-row" v-loading="statsLoading">
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

      <div v-if="stats.overdue_count > 0" class="overdue-bar">
        <el-icon class="overdue-icon"><WarningFilled /></el-icon>
        <span>
          当前有 <b>{{ stats.overdue_count }}</b> 期账单逾期未结清，涉及金额
          <b>¥{{ money(stats.overdue_amount) }}</b>
        </span>
        <el-button link type="danger" @click="goCollect">查看催收清单 →</el-button>
      </div>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.status" placeholder="收款状态" clearable class="sel" @change="search">
        <el-option v-for="(m, k) in statusOptions" :key="k" :label="m" :value="k" />
      </el-select>

      <el-input
        v-model="query.keyword"
        placeholder="案号 / 案件标题"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-button class="warn-btn" plain type="warning" @click="goCollect">
        <el-icon><Bell /></el-icon>催收清单
      </el-button>

      <div class="spacer" />

      <el-button type="primary" @click="openForm">
        <el-icon><Plus /></el-icon>新建收费方案
      </el-button>
    </div>

    <!-- 收费方案列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="案件" min-width="240" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="case-cell">
              <el-link type="primary" :underline="false" @click="goDetail(row.id)">
                {{ row.case_title || `案件 #${row.case_id}` }}
              </el-link>
              <span class="case-no">{{ row.case_no || '—' }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="client_name" label="委托客户" min-width="110" show-overflow-tooltip>
          <template #default="{ row }">{{ row.client_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="收费方式" width="110" align="center">
          <template #default="{ row }">
            <el-tag :type="FEE_TYPE_META[row.fee_type]?.type || 'info'" effect="plain" size="small">
              {{ FEE_TYPE_META[row.fee_type]?.label || row.fee_type }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="收费总额" width="130" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ money(row.total_amount) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="已收 / 未收" width="160" align="right">
          <template #default="{ row }">
            <div class="paid-cell">
              <span class="paid">¥{{ money(row.paid_total) }}</span>
              <span class="unpaid">¥{{ money(unpaidOf(row)) }}</span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="收款进度" width="170">
          <template #default="{ row }">
            <div class="progress-cell">
              <el-progress
                :percentage="progressPercent(row.due_total, row.paid_total)"
                :stroke-width="6"
                :show-text="false"
                :color="progressColor(row)"
              />
              <span class="progress-text">
                {{ progressPercent(row.due_total, row.paid_total) }}%
                <span class="period-count">（{{ row.period_count || 0 }} 期）</span>
              </span>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="planStatusMeta(row).type" effect="light" size="small">
              {{ planStatusMeta(row).label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" width="140">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="90" fixed="right" align="center">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !rows.length" description="暂无收费方案" :image-size="100" />

      <div v-if="total > 0" class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <!-- 新建收费方案 -->
    <FeePlanForm v-model="formVisible" @saved="onSaved" />
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, Plus, Bell, WarningFilled } from '@element-plus/icons-vue'
import { listFeePlans, getBillingStats } from '@/api/billing'
import {
  FEE_TYPE_META,
  formatTime,
  money,
  num,
  planStatusMeta,
  progressPercent,
} from '@/utils/billing'
import FeePlanForm from './FeePlanForm.vue'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const rows = ref([])
const total = ref(0)

const formVisible = ref(false)

const statsLoading = ref(false)
const stats = ref({
  month: '',
  month_income: 0,
  total_due: 0,
  total_paid: 0,
  total_unpaid: 0,
  collection_rate: 0,
  overdue_amount: 0,
  overdue_count: 0,
})

const now = new Date()
const statsMonth = ref(
  `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
)

const query = reactive({
  status: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

// 收款状态筛选（overdue 由催收清单页面承载）
const statusOptions = {
  unpaid: '未收款',
  partial: '部分收款',
  paid: '已结清',
  overdue: '有逾期',
}

const statCards = computed(() => [
  {
    label: '当月实收',
    value: `¥${money(stats.value.month_income)}`,
    icon: 'Money',
    bg: '#faf3e7',
    color: '#a5813d',
  },
  {
    label: '累计应收',
    value: `¥${money(stats.value.total_due)}`,
    icon: 'Tickets',
    bg: '#eef2fa',
    color: '#1d2b47',
  },
  {
    label: '累计未收',
    value: `¥${money(stats.value.total_unpaid)}`,
    icon: 'Wallet',
    bg: '#faeef0',
    color: '#993556',
    danger: num(stats.value.total_unpaid) > 0,
  },
  {
    label: '回款率',
    value: `${num(stats.value.collection_rate).toFixed(2)}%`,
    icon: 'TrendCharts',
    bg: '#eaf5ef',
    color: '#1D9E75',
  },
])

function unpaidOf(row) {
  return Math.max(0, num(row.due_total) - num(row.paid_total))
}

function progressColor(row) {
  const p = progressPercent(row.due_total, row.paid_total)
  if (p >= 100) return '#1D9E75'
  if (p > 0) return '#c9a55c'
  return '#c0c4cc'
}

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.status) delete params.status
    if (!params.keyword) delete params.keyword
    const data = await listFeePlans(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  statsLoading.value = true
  try {
    const [year, month] = (statsMonth.value || '').split('-')
    stats.value = await getBillingStats({
      year: year ? Number(year) : undefined,
      month: month ? Number(month) : undefined,
    })
  } finally {
    statsLoading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function openForm() {
  formVisible.value = true
}

function onSaved() {
  formVisible.value = false
  load()
  loadStats()
}

function base() {
  return route.path.startsWith('/admin') ? '/admin' : '/lawyer'
}

function goDetail(id) {
  router.push(`${base()}/billing/${id}`)
}

function goCollect() {
  router.push(`${base()}/billing/collect`)
}

load()
loadStats()
</script>

<style scoped>
.billing-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.stat-block {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.stat-caption {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.caption-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.month-pick {
  width: 140px;
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

.overdue-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 16px;
  background: #fdf2f2;
  border: 1px solid #f5d6d6;
  border-radius: 10px;
  font-size: 13px;
  color: #993556;
}

.overdue-icon {
  color: var(--el-color-danger);
  font-size: 16px;
}

.overdue-bar .el-button {
  margin-left: auto;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar .kw {
  width: 220px;
}

.filter-bar .sel {
  width: 150px;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
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

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.paid-cell {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 2px;
  font-size: 13px;
}

.paid-cell .paid {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.paid-cell .unpaid {
  color: var(--el-color-danger);
}

.progress-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.progress-text {
  font-size: 12px;
  color: var(--brand-muted);
}

.period-count {
  color: #b3b9c6;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
