<template>
  <div class="my-contracts">
    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="card-head">
          <span>我的合同</span>
          <span class="sub">共 {{ rows.length }} 份</span>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="合同名称" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-link type="primary" :underline="false" @click="goDetail(row.id)">{{ row.name }}</el-link>
          </template>
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

        <el-table-column label="操作" width="120" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !rows.length" description="暂无合同" :image-size="100" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listMyContracts } from '@/api/contracts'
import { useDictStore } from '@/stores/dict'

const router = useRouter()

const loading = ref(false)
const rows = ref([])

const statusMeta = {
  draft: { label: '草稿', type: 'info' },
  active: { label: '生效中', type: 'success' },
  expired: { label: '已到期', type: 'warning' },
  terminated: { label: '已终止', type: 'danger' },
}

const dictStore = useDictStore()
dictStore.ensure()

async function load() {
  loading.value = true
  try {
    rows.value = await listMyContracts()
  } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/client/contracts/${id}`)
}

function formatDate(s) {
  if (!s) return '—'
  return String(s).slice(0, 10)
}

function formatAmount(v) {
  if (v === null || v === undefined) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

onMounted(load)
</script>

<style scoped>
.my-contracts {
  display: flex;
  flex-direction: column;
  gap: 16px;
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
  font-size: 13px;
  font-weight: 400;
  color: var(--brand-muted);
}

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.date-range {
  font-size: 13px;
  color: var(--brand-muted);
}
</style>
