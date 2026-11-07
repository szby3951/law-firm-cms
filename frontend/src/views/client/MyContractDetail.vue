<template>
  <div class="my-contract-detail" v-loading="loading">
    <div class="back-bar">
      <el-button link @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>返回我的合同
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 合同信息 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>合同信息</span>
            <el-tag :type="statusMeta[detail.status]?.type" effect="light" size="small">
              {{ statusMeta[detail.status]?.label }}
            </el-tag>
          </div>
        </template>

        <div class="contract-head">
          <div class="contract-title">{{ detail.name }}</div>
          <div class="contract-sub">创建于 {{ formatTime(detail.created_at) }}</div>
        </div>

        <el-descriptions :column="3" border class="desc">
          <el-descriptions-item label="合同类型">
            {{ dictStore.labelOf('contract_type', detail.contract_type, '其他') }}
          </el-descriptions-item>
          <el-descriptions-item label="合同金额">
            <span class="amount">¥{{ formatAmount(detail.amount) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="当前状态">
            {{ statusMeta[detail.status]?.label }}
          </el-descriptions-item>
          <el-descriptions-item label="生效日期">{{ formatDate(detail.start_date) }}</el-descriptions-item>
          <el-descriptions-item label="到期日期">{{ formatDate(detail.end_date) }}</el-descriptions-item>
          <el-descriptions-item label="委托客户">{{ detail.client_name || '—' }}</el-descriptions-item>
          <el-descriptions-item label="关联案件">
            {{ detail.case_title || (detail.case_id ? `案件 #${detail.case_id}` : '—') }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 合同文件（只读） -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head"><span>合同文件</span></div>
        </template>
        <div v-if="detail.file_url" class="file-box">
          <el-icon class="file-icon"><Document /></el-icon>
          <div class="file-actions">
            <el-button type="primary" size="small" @click="previewFile">查看</el-button>
            <el-button size="small" @click="downloadFile">下载</el-button>
          </div>
        </div>
        <el-empty v-else description="尚未上传合同文件" :image-size="80" />
      </el-card>

      <!-- AI 审查报告（只读） -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head"><span>AI 风险审查报告</span></div>
        </template>
        <template v-if="detail.ai_review_report">
          <div class="review-summary">
            <el-tag v-if="detail.ai_review_at" type="info" effect="plain" size="small">
              审查时间 {{ formatTime(detail.ai_review_at) }}
            </el-tag>
          </div>
          <ContractReviewReport :report="detail.ai_review_report" />
        </template>
        <el-empty v-else description="暂无 AI 审查报告" :image-size="80" />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Document } from '@element-plus/icons-vue'
import { getMyContract, downloadContractFile } from '@/api/contracts'
import ContractReviewReport from '@/components/ContractReviewReport.vue'
import { useDictStore } from '@/stores/dict'

const route = useRoute()
const id = Number(route.params.id)

const loading = ref(false)
const detail = ref(null)

const statusMeta = {
  draft: { label: '草稿', type: 'info' },
  active: { label: '生效中', type: 'success' },
  expired: { label: '已到期', type: 'warning' },
  terminated: { label: '已终止', type: 'danger' },
}

const dictStore = useDictStore()
dictStore.ensure()

const PREVIEWABLE = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'txt']

function extOf(name) {
  const i = (name || '').lastIndexOf('.')
  return i === -1 ? '' : name.slice(i + 1).toLowerCase()
}

async function load() {
  loading.value = true
  try {
    detail.value = await getMyContract(id)
  } finally {
    loading.value = false
  }
}

async function fetchBlob() {
  const res = await downloadContractFile(id)
  return res.data instanceof Blob ? res.data : new Blob([res.data])
}

async function previewFile() {
  const name = detail.value.file_url || ''
  if (!PREVIEWABLE.includes(extOf(name))) {
    ElMessage.info('该格式暂不支持在线预览，请下载后查看')
    return
  }
  try {
    const blob = await fetchBlob()
    const url = window.URL.createObjectURL(blob)
    window.open(url, '_blank')
    setTimeout(() => window.URL.revokeObjectURL(url), 60 * 1000)
  } catch {
    // 错误已由拦截器提示
  }
}

async function downloadFile() {
  try {
    const blob = await fetchBlob()
    const url = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = detail.value.name || '合同文件'
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => window.URL.revokeObjectURL(url), 60 * 1000)
  } catch {
    // 错误已由拦截器提示
  }
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

onMounted(load)
</script>

<style scoped>
.my-contract-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.back-bar {
  margin-bottom: -4px;
}

.section {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.contract-head {
  margin-bottom: 20px;
}

.contract-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
}

.contract-sub {
  font-size: 13px;
  color: var(--brand-muted);
  margin-top: 8px;
}

.desc {
  margin-top: 4px;
}

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.file-box {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
}

.file-icon {
  font-size: 28px;
  color: var(--brand-navy-soft);
}

.file-actions {
  display: flex;
  gap: 8px;
}

.review-summary {
  margin-bottom: 12px;
}

</style>
