<template>
  <div class="case-detail" v-loading="loading">
    <!-- 返回 -->
    <div class="back-bar">
      <el-button link @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>返回案件列表
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 基本信息卡 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>案件信息</span>
            <div class="head-actions">
              <el-tag :type="statusMeta[detail.status]?.type" effect="light" size="small">
                {{ statusMeta[detail.status]?.label }}
              </el-tag>
              <el-button v-if="!isClient" link type="primary" @click="statusVisible = true">
                <el-icon><Refresh /></el-icon>状态流转
              </el-button>
              <el-button v-if="!isClient" link type="primary" @click="askAi">
                <el-icon><MagicStick /></el-icon>问 AI
              </el-button>
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

      <!-- AI 案件摘要（9.6）：按承办律师账号隔离，客户不可见 -->
      <CaseSummaryCard v-if="!isClient" :case-id="id" />

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

      <!-- 案件时间轴 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>案件时间线</span>
            <el-button v-if="!isClient" type="primary" size="small" @click="eventVisible = true">
              <el-icon><Plus /></el-icon>登记事件
            </el-button>
          </div>
        </template>
        <CaseTimeline :events="detail.events || []" />
      </el-card>

      <!-- 附件 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>案件材料</span>
            <el-upload
              v-if="!isClient"
              :show-file-list="false"
              :http-request="handleUpload"
              accept="*"
            >
              <el-button type="primary" size="small" plain>
                <el-icon><Upload /></el-icon>上传文件
              </el-button>
            </el-upload>
          </div>
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

    <!-- 状态流转弹窗 -->
    <el-dialog v-model="statusVisible" title="案件状态流转" width="440px" :close-on-click-modal="false">
      <el-form label-width="92px" label-position="right">
        <el-form-item label="当前状态">
          <el-tag :type="statusMeta[detail?.status]?.type" effect="light" size="small">
            {{ statusMeta[detail?.status]?.label }}
          </el-tag>
        </el-form-item>
        <el-form-item label="流转到">
          <el-select v-model="targetStatus" placeholder="选择目标状态" style="width: 100%">
            <el-option
              v-for="s in allowedStatuses"
              :key="s"
              :label="statusMeta[s].label"
              :value="s"
            />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="statusVisible = false">取消</el-button>
        <el-button type="primary" :loading="statusSubmitting" @click="submitStatus">确认流转</el-button>
      </template>
    </el-dialog>

    <!-- 事件登记弹窗 -->
    <EventDialog v-model="eventVisible" :case-id="id" @saved="load" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, MagicStick, Plus, Refresh, Upload } from '@element-plus/icons-vue'
import { getCase, updateCaseStatus, uploadCaseFile, downloadCaseFile } from '@/api/cases'
import { useUserStore } from '@/stores/user'
import { useAiAssistantStore } from '@/stores/aiAssistant'
import CaseSummaryCard from '@/components/CaseSummaryCard.vue'
import CaseTimeline from './CaseTimeline.vue'
import EventDialog from './EventDialog.vue'

const route = useRoute()
const id = Number(route.params.id)
const userStore = useUserStore()
const aiStore = useAiAssistantStore()
const isClient = computed(() => userStore.role === 'client')

const loading = ref(false)
const detail = ref(null)

const statusVisible = ref(false)
const statusSubmitting = ref(false)
const targetStatus = ref('')
const eventVisible = ref(false)

const statusMeta = {
  consulting: { label: '咨询中', type: 'primary' },
  filed: { label: '已立案', type: 'warning' },
  handling: { label: '办理中', type: 'success' },
  pending_close: { label: '待结案', type: 'info' },
  closed: { label: '已结案', type: 'success' },
  withdrawn: { label: '已退案', type: 'danger' },
}

// 状态机（与后端保持一致）
const TRANSITIONS = {
  consulting: ['filed', 'withdrawn'],
  filed: ['handling', 'withdrawn'],
  handling: ['pending_close', 'withdrawn'],
  pending_close: ['closed', 'handling', 'withdrawn'],
  closed: [],
  withdrawn: [],
}

const attachments = computed(() => detail.value?.attachments || [])

const allowedStatuses = computed(() => {
  if (!detail.value) return []
  return TRANSITIONS[detail.value.status] || []
})

async function load() {
  loading.value = true
  try {
    detail.value = await getCase(id)
  } finally {
    loading.value = false
  }
}

// 9.8.4 页内快捷入口：把案件上下文带进全局 AI 悬浮窗，律师可改问法再发
function askAi() {
  const d = detail.value
  if (!d) return
  const parts = [`我在办理案件「${d.title}」（案号 ${d.case_no}）`]
  if (d.case_cause) parts.push(`案由：${d.case_cause}`)
  if (d.court) parts.push(`受理法院：${d.court}`)
  aiStore.open(
    `${parts.join('，')}。请结合相关法条，说明下一步的程序节点、举证要点与需要防范的时间风险。`,
  )
}

async function submitStatus() {
  if (!targetStatus.value) {
    ElMessage.warning('请选择目标状态')
    return
  }
  // 前端先行校验（非法流转直接提示，不发请求）
  if (!allowedStatuses.value.includes(targetStatus.value)) {
    ElMessage.error(`不能从「${statusMeta[detail.value.status].label}」流转到该状态`)
    return
  }
  statusSubmitting.value = true
  try {
    await updateCaseStatus(id, targetStatus.value)
    ElMessage.success('状态已更新')
    statusVisible.value = false
    targetStatus.value = ''
    load()
  } finally {
    statusSubmitting.value = false
  }
}

async function handleUpload({ file }) {
  try {
    await uploadCaseFile(id, file)
    ElMessage.success('文件已上传')
    load()
  } catch {
    // 错误已由拦截器提示
  }
}

// 根据扩展名判断是否可在浏览器内联预览
const PREVIEWABLE = ['pdf', 'jpg', 'jpeg', 'png', 'gif', 'webp', 'txt']

function extOf(name) {
  const i = name.lastIndexOf('.')
  return i === -1 ? '' : name.slice(i + 1).toLowerCase()
}

function isPreviewable(row) {
  return PREVIEWABLE.includes(extOf(row.file_name || ''))
}

// 获取 blob 并生成本地 URL
async function fetchBlobUrl(row) {
  const res = await downloadCaseFile(row.id)
  const blob = res.data instanceof Blob ? res.data : new Blob([res.data])
  return window.URL.createObjectURL(blob)
}

// 查看：PDF/图片在新标签页内联预览；其他类型提示下载
async function previewFile(row) {
  if (!isPreviewable(row)) {
    ElMessage.info('该格式暂不支持在线预览，请下载后查看')
    return
  }
  try {
    const url = await fetchBlobUrl(row)
    window.open(url, '_blank')
    // 延迟释放，避免打开瞬间 URL 失效
    setTimeout(() => window.URL.revokeObjectURL(url), 60 * 1000)
  } catch {
    // 错误已由拦截器提示
  }
}

// 下载：保存到本地
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
.case-detail {
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
