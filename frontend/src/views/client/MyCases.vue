<template>
  <div class="my-cases">
    <div class="welcome-card">
      <div class="welcome-text">
        <h2>我的案件</h2>
        <p>您的委托事务进展，我们会及时同步给您</p>
      </div>
      <div class="welcome-badge">委托人</div>
    </div>

    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" style="width: 100%">
        <el-table-column prop="case_no" label="案号" width="150">
          <template #default="{ row }">
            <span class="case-no">{{ row.case_no }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="title" label="案件标题" min-width="200" show-overflow-tooltip />

        <el-table-column prop="case_cause" label="案由" min-width="110">
          <template #default="{ row }">{{ row.case_cause || '—' }}</template>
        </el-table-column>

        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.case_type === 'litigation' ? 'primary' : 'info'" effect="plain" size="small">
              {{ row.case_type === 'litigation' ? '诉讼' : '非诉' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type" effect="light" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="立案时间" min-width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="100" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">查看进度</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !rows.length" description="暂无委托案件" :image-size="100" />
    </el-card>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { listMyCases } from '@/api/cases'

const router = useRouter()
const loading = ref(false)
const rows = ref([])

const statusMeta = {
  consulting: { label: '咨询中', type: 'primary' },
  filed: { label: '已立案', type: 'warning' },
  handling: { label: '办理中', type: 'success' },
  pending_close: { label: '待结案', type: 'info' },
  closed: { label: '已结案', type: 'success' },
  withdrawn: { label: '已退案', type: 'danger' },
}

async function load() {
  loading.value = true
  try {
    rows.value = await listMyCases()
  } finally {
    loading.value = false
  }
}

function goDetail(id) {
  router.push(`/client/cases/${id}`)
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<style scoped>
.my-cases {
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
}

.welcome-badge {
  padding: 6px 16px;
  border: 1px solid rgba(201, 165, 92, 0.5);
  border-radius: 20px;
  color: var(--brand-gold-light);
  font-size: 12px;
  letter-spacing: 2px;
}

.table-card {
  border-radius: 12px;
}

.case-no {
  font-weight: 500;
  color: var(--brand-navy-soft);
  font-family: 'SFMono-Regular', Consolas, monospace;
}
</style>
