<template>
  <div class="my-case-detail" v-loading="loading">
    <div class="back-bar">
      <el-button link @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>返回我的案件
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 案件信息 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>案件信息</span>
            <div class="head-actions">
              <el-button link type="primary" @click="askAi">
                <el-icon><MagicStick /></el-icon>咨询 AI
              </el-button>
              <el-tag :type="statusMeta[detail.status]?.type" effect="light" size="small">
                {{ statusMeta[detail.status]?.label }}
              </el-tag>
            </div>
          </div>
        </template>

        <div class="case-head">
          <div class="case-title">
            <span class="no">{{ detail.case_no }}</span>
            <span class="title">{{ detail.title }}</span>
          </div>
          <div class="case-sub">
            立案于 {{ formatTime(detail.created_at) }}
            <template v-if="detail.closed_at"> · 结案于 {{ formatTime(detail.closed_at) }}</template>
          </div>
        </div>

        <el-descriptions :column="3" border class="desc">
          <el-descriptions-item label="案由">{{ detail.case_cause || '—' }}</el-descriptions-item>
          <el-descriptions-item label="案件类型">
            {{ detail.case_type === 'litigation' ? '诉讼' : '非诉' }}
          </el-descriptions-item>
          <el-descriptions-item label="标的额">
            <span class="amount">¥{{ formatAmount(detail.amount) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="受理法院">{{ detail.court || '—' }}</el-descriptions-item>
          <el-descriptions-item label="对方当事人">{{ detail.opposing_party || '—' }}</el-descriptions-item>
          <el-descriptions-item label="当前状态">
            {{ statusMeta[detail.status]?.label }}
          </el-descriptions-item>
          <el-descriptions-item label="案情描述" :span="3">
            {{ detail.description || '—' }}
          </el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- 承办律师 -->
      <el-card v-if="detail.lawyers && detail.lawyers.length" shadow="never" class="section">
        <template #header>
          <div class="card-head"><span>承办律师</span></div>
        </template>
        <div class="lawyer-tags">
          <el-tag
            v-for="l in detail.lawyers"
            :key="`${l.lawyer_id}-${l.duty}`"
            :type="l.duty === 'lead' ? 'primary' : 'info'"
            effect="light"
          >
            {{ l.duty === 'lead' ? '主办' : '协办' }} · {{ l.lawyer_name || l.lawyer_id }}
          </el-tag>
        </div>
      </el-card>

      <!-- 案件时间线 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head"><span>案件进展时间线</span></div>
        </template>
        <CaseTimeline :events="detail.events || []" />
      </el-card>

      <!-- 案件材料（只读，可查看/下载） -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head"><span>案件材料</span></div>
        </template>
        <el-table v-if="attachments.length" :data="attachments" size="small">
          <el-table-column prop="file_name" label="文件名" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">
              <el-link type="primary" :underline="false" @click="previewFile(row)">
                {{ row.file_name }}
              </el-link>
            </template>
          </el-table-column>
          <el-table-column label="大小" width="120">
            <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
          </el-table-column>
          <el-table-column prop="created_at" label="上传时间" width="160">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>
          <el-table-column label="操作" width="120" align="center">
            <template #default="{ row }">
              <el-button link type="primary" size="small" @click="previewFile(row)">查看</el-button>
              <el-button link type="primary" size="small" @click="downloadFile(row)">下载</el-button>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-else description="暂无案件材料" :image-size="80" />
      </el-card>
    </template>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, MagicStick } from '@element-plus/icons-vue'
import { getMyCase, downloadCaseFile } from '@/api/cases'
import { useAiAssistantStore } from '@/stores/aiAssistant'
import CaseTimeline from '@/views/lawyer/CaseTimeline.vue'

const route = useRoute()
const id = Number(route.params.id)
const aiStore = useAiAssistantStore()

const loading = ref(false)
const detail = ref(null)

const attachments = computed(() => detail.value?.attachments || [])

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
    detail.value = await getMyCase(id)
  } finally {
    loading.value = false
  }
}

// 9.8.4：把案件背景带进悬浮窗，客户只需补一句自己的疑问
function askAi() {
  const d = detail.value
  if (!d) return
  aiStore.open(
    `我委托律师办理的案件「${d.title}」，目前的进展是「${statusMeta[d.status]?.label || '处理中'}」。我想了解这类案件一般要经过哪些阶段、我需要配合准备什么材料。`,
  )
}

// 可内联预览的扩展名
const PREVIEWABLE = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'txt']

function extOf(name) {
  const i = name.lastIndexOf('.')
  return i === -1 ? '' : name.slice(i + 1).toLowerCase()
}

function isPreviewable(row) {
  return PREVIEWABLE.includes(extOf(row.file_name || ''))
}

async function fetchBlobUrl(row) {
  const res = await downloadCaseFile(row.id)
  const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
  return window.URL.createObjectURL(blob)
}

async function previewFile(row) {
  if (!isPreviewable(row)) {
    ElMessage.info('该格式暂不支持在线预览，请下载后查看')
    return
  }
  try {
    const url = await fetchBlobUrl(row)
    window.open(url, '_blank')
    setTimeout(() => window.URL.revokeObjectURL(url), 60 * 1000)
  } catch {
    // 错误已由拦截器提示
  }
}

async function downloadFile(row) {
  try {
    const url = await fetchBlobUrl(row)
    const a = document.createElement('a')
    a.href = url
    a.download = row.file_name || '下载文件'
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

function formatAmount(v) {
  if (v === null || v === undefined) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let n = bytes
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024
    i++
  }
  return `${n.toFixed(1)} ${units[i]}`
}

onMounted(load)
</script>

<style scoped>
.my-case-detail {
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

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.case-head {
  margin-bottom: 20px;
}

.case-title {
  display: flex;
  align-items: center;
  gap: 12px;
}

.case-title .no {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 14px;
  background: var(--brand-navy-soft);
  color: var(--brand-gold-light);
  padding: 2px 10px;
  border-radius: 6px;
}

.case-title .title {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
}

.case-sub {
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

.lawyer-tags {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}
</style>
