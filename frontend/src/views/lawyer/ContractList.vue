<template>
  <div class="contract-list">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.status" placeholder="合同状态" clearable class="sel" @change="search">
        <el-option v-for="(m, k) in statusMeta" :key="k" :label="m.label" :value="k" />
      </el-select>

      <el-select
        v-model="query.contract_type"
        placeholder="合同类型"
        clearable
        class="sel"
        @change="search"
      >
        <el-option
          v-for="o in typeOptions"
          :key="o.value"
          :label="o.label"
          :value="o.value"
        />
      </el-select>

      <el-input
        v-model="query.keyword"
        placeholder="合同名称关键词"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-button class="warn-btn" plain type="warning" @click="loadExpiring">
        <el-icon><Bell /></el-icon>到期预警
      </el-button>

      <div class="spacer" />

      <el-button type="primary" @click="openForm()">
        <el-icon><Plus /></el-icon>新建合同
      </el-button>
    </div>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="合同名称" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="goDetail(row.id)">{{ row.name }}</el-link>
          </template>
        </el-table-column>

        <el-table-column prop="client_name" label="委托客户" min-width="120" show-overflow-tooltip>
          <template #default="{ row }">{{ row.client_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="类型" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="row.contract_type ? 'primary' : 'info'" effect="plain" size="small">
              {{ dictStore.labelOf('contract_type', row.contract_type, '其他') }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="合同金额" width="140" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ formatAmount(row.amount) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="有效期" width="200">
          <template #default="{ row }">
            <span class="date-range">
              {{ formatDate(row.start_date) }} ~ {{ formatDate(row.end_date) }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type" effect="light" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="是否上传文件" width="110" align="center">
          <template #default="{ row }">
            <el-icon v-if="row.file_url" class="has-file"><DocumentChecked /></el-icon>
            <span v-else class="no-file">未上传</span>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" min-width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">详情</el-button>
            <el-button link type="primary" @click="openForm(row)">编辑</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
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

    <!-- 新建/编辑合同表单 -->
    <ContractForm v-model="formVisible" :contract="editing" @saved="onSaved" />

    <!-- 到期预警弹窗 -->
    <el-dialog v-model="expiringVisible" title="到期合同预警" width="640px" :close-on-click-modal="false">
      <el-alert
        v-if="!expiring.length"
        title="暂无即将到期的合同"
        type="success"
        :closable="false"
        show-icon
      />
      <el-table v-else :data="expiring" size="small" v-loading="expiringLoading">
        <el-table-column prop="name" label="合同名称" min-width="200" show-overflow-tooltip />
        <el-table-column label="到期日期" width="120">
          <template #default="{ row }">
            <span :class="{ 'expiring-soon': isSoon(row.end_date) }">{{ formatDate(row.end_date) }}</span>
          </template>
        </el-table-column>
        <el-table-column label="剩余" width="100" align="center">
          <template #default="{ row }">{{ daysLeft(row.end_date) }} 天</template>
        </el-table-column>
        <el-table-column label="操作" width="100" align="center">
          <template #default="{ row }">
            <el-button link type="primary" size="small" @click="goDetailFromExpiring(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <template #footer>
        <el-button @click="expiringVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { Search, Plus, Bell, DocumentChecked } from '@element-plus/icons-vue'
import { listContracts, listExpiringContracts } from '@/api/contracts'
import ContractForm from './ContractForm.vue'
import { useDictStore } from '@/stores/dict'

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const rows = ref([])
const total = ref(0)

const formVisible = ref(false)
const editing = ref(null)

const expiringVisible = ref(false)
const expiringLoading = ref(false)
const expiring = ref([])

const query = reactive({
  status: '',
  contract_type: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

const dictStore = useDictStore()

const statusMeta = {
  draft: { label: '草稿', type: 'info' },
  active: { label: '生效中', type: 'success' },
  expired: { label: '已到期', type: 'warning' },
  terminated: { label: '已终止', type: 'danger' },
}

// 合同类型候选与标签都跟管理端字典走
const typeOptions = computed(() => dictStore.options('contract_type'))
dictStore.ensure()

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.status) delete params.status
    if (!params.contract_type) delete params.contract_type
    if (!params.keyword) delete params.keyword
    const data = await listContracts(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function openForm(row = null) {
  editing.value = row
  formVisible.value = true
}

function onSaved() {
  formVisible.value = false
  editing.value = null
  load()
}

async function loadExpiring() {
  expiringVisible.value = true
  expiringLoading.value = true
  try {
    expiring.value = await listExpiringContracts(30)
  } finally {
    expiringLoading.value = false
  }
}

function goDetail(id) {
  const base = route.path.startsWith('/admin') ? '/admin' : '/lawyer'
  router.push(`${base}/contracts/${id}`)
}

function goDetailFromExpiring(row) {
  expiringVisible.value = false
  goDetail(row.id)
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

function formatDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 10)
}

function formatAmount(v) {
  if (v === null || v === undefined) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function daysLeft(endDate) {
  if (!endDate) return '—'
  const end = new Date(endDate)
  const now = new Date()
  return Math.ceil((end - now) / (1000 * 60 * 60 * 24))
}

function isSoon(endDate) {
  const d = daysLeft(endDate)
  return typeof d === 'number' && d <= 7
}

load()
</script>

<style scoped>
.contract-list {
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

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.date-range {
  font-size: 13px;
  color: var(--brand-muted);
}

.has-file {
  color: var(--brand-gold-deep);
  font-size: 16px;
}

.no-file {
  color: var(--brand-muted);
  font-size: 12px;
}

.expiring-soon {
  color: var(--el-color-danger);
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
