<template>
  <div class="contract-detail" v-loading="loading">
    <!-- 返回 -->
    <div class="back-bar">
      <el-button link @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>返回合同列表
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 基本信息卡 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>合同信息</span>
            <div class="head-actions">
              <el-tag :type="statusMeta[detail.status]?.type" effect="light" size="small">
                {{ statusMeta[detail.status]?.label }}
              </el-tag>
              <el-button link type="primary" @click="editVisible = true">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <el-button link type="primary" @click="askAi">
                <el-icon><MagicStick /></el-icon>问 AI
              </el-button>
            </div>
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

      <!-- 合同文件 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>合同文件</span>
            <el-upload :show-file-list="false" :http-request="handleUpload" accept=".pdf,.doc,.docx">
              <el-button type="primary" size="small" plain>
                <el-icon><Upload /></el-icon>上传文件
              </el-button>
            </el-upload>
          </div>
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

      <!-- AI 审查报告 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>AI 风险审查报告</span>
            <div class="head-actions">
              <el-button
                type="primary"
                size="small"
                :loading="reviewing"
                :disabled="reviewing"
                @click="startReview()"
              >
                <el-icon v-if="!reviewing"><MagicStick /></el-icon>
                {{ reviewing ? '审查中…' : detail.ai_review_report ? '重新审查' : 'AI 审查' }}
              </el-button>
              <el-button size="small" :disabled="reviewing" @click="textVisible = true">
                粘贴正文审查
              </el-button>
              <el-button link type="primary" size="small" @click="reviewVisible = true">
                手动录入
              </el-button>
            </div>
          </div>
        </template>

        <!-- 审查进度 -->
        <div v-if="reviewing" class="review-progress">
          <el-progress
            :percentage="reviewPercent"
            :stroke-width="6"
            :show-text="false"
            striped
            striped-flow
          />
          <span class="progress-text">{{ reviewStage || '正在审查…' }}</span>
        </div>

        <el-alert
          v-for="(note, index) in reviewWarnings"
          :key="index"
          :title="note"
          type="warning"
          :closable="false"
          show-icon
          class="review-warning"
        />

        <template v-if="detail.ai_review_report">
          <div class="review-summary">
            <el-tag v-if="detail.ai_review_at" type="info" effect="plain" size="small">
              审查时间 {{ formatTime(detail.ai_review_at) }}
            </el-tag>
          </div>
          <ContractReviewReport :report="detail.ai_review_report" />
        </template>
        <el-empty
          v-else
          description="尚未审查。点击「AI 审查」读取已上传的合同文件，或粘贴合同正文。"
          :image-size="80"
        />
      </el-card>
    </template>

    <!-- 编辑合同弹窗 -->
    <ContractForm v-model="editVisible" :contract="detail" @saved="load" />

    <!-- 粘贴正文审查 -->
    <el-dialog
      v-model="textVisible"
      title="粘贴合同正文审查"
      width="760px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="扫描件 PDF 无法提取文字时，可把合同正文粘贴到这里；正文越完整，条款定位越准确。"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-input
        v-model="reviewText"
        type="textarea"
        :rows="12"
        maxlength="100000"
        show-word-limit
        placeholder="粘贴合同全文（含「第X条」标题效果最好）"
      />
      <el-input
        v-model="reviewFocus"
        style="margin-top: 12px"
        maxlength="500"
        placeholder="特别关注点（可选），如：重点看违约金比例与管辖约定"
      />
      <template #footer>
        <el-button @click="textVisible = false">取消</el-button>
        <el-button
          type="primary"
          :loading="reviewing"
          :disabled="reviewText.trim().length < 50"
          @click="submitTextReview"
        >
          开始审查
        </el-button>
      </template>
    </el-dialog>

    <!-- 手动录入审查报告 -->
    <el-dialog
      v-model="reviewVisible"
      title="手动录入审查报告"
      width="640px"
      :close-on-click-modal="false"
    >
      <el-alert
        title="粘贴结构化 JSON 审查报告（含 summary 摘要与 risks 风险项）"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 12px"
      />
      <el-input
        v-model="reportText"
        type="textarea"
        :rows="12"
        placeholder='{"summary":"整体风险中等","risks":[{"clause":"第四条 违约责任","quote":"……","risk":"违约金比例过高","level":"high","suggestion":"……"}]}'
      />
      <template #footer>
        <el-button @click="reviewVisible = false">取消</el-button>
        <el-button type="primary" :loading="reviewSubmitting" @click="submitReview">
          保存报告
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  ArrowLeft,
  Edit,
  Upload,
  Document,
  MagicStick,
} from '@element-plus/icons-vue'
import {
  getContract,
  uploadContractFile,
  downloadContractFile,
  saveContractReview,
} from '@/api/contracts'
import { reviewContract } from '@/api/ai'
import { useAiAssistantStore } from '@/stores/aiAssistant'
import ContractForm from './ContractForm.vue'
import ContractReviewReport from '@/components/ContractReviewReport.vue'
import { useDictStore } from '@/stores/dict'

const route = useRoute()
const id = Number(route.params.id)
const aiStore = useAiAssistantStore()

const loading = ref(false)
const detail = ref(null)

const editVisible = ref(false)
const reviewVisible = ref(false)
const reviewSubmitting = ref(false)
const reportText = ref('')

// AI 审查
const reviewing = ref(false)
const reviewPercent = ref(0)
const reviewStage = ref('')
const reviewWarnings = ref([])
const textVisible = ref(false)
const reviewText = ref('')
const reviewFocus = ref('')

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
    detail.value = await getContract(id)
  } finally {
    loading.value = false
  }
}

// 9.8.4 页内快捷入口：合同上下文预填到全局 AI 悬浮窗
function askAi() {
  const d = detail.value
  if (!d) return
  const parts = [`我在审查合同「${d.name}」`]
  if (d.contract_type) {
    const label = dictStore.labelOf('contract_type', d.contract_type)
    if (label) parts.push(`类型：${label}`)
  }
  if (d.amount) parts.push(`金额：¥${formatAmount(d.amount)}`)
  if (d.client_name) parts.push(`委托客户：${d.client_name}`)
  aiStore.open(
    `${parts.join('，')}。请说明此类合同常见的法律风险点、审查时要重点核对的条款，以及缺失条款可能带来的后果。`,
  )
}

async function handleUpload({ file }) {
  try {
    await uploadContractFile(id, file)
    ElMessage.success('合同文件已上传')
    load()
  } catch {
    // 错误已由拦截器提示
  }
}

async function fetchBlob() {
  const res = await downloadContractFile(id)
  return res.data instanceof Blob ? res.data : new Blob([res.data])
}

async function previewFile() {
  // 从 file_url 推断扩展名
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

async function submitReview() {
  let report
  try {
    report = JSON.parse(reportText.value)
  } catch {
    ElMessage.error('报告内容不是合法的 JSON')
    return
  }
  reviewSubmitting.value = true
  try {
    await saveContractReview(id, report)
    ElMessage.success('审查报告已保存')
    reviewVisible.value = false
    reportText.value = ''
    load()
  } finally {
    reviewSubmitting.value = false
  }
}

/**
 * 触发一次 AI 审查。
 *
 * 后端是 SSE：meta → precheck → (stage → progress)* → done/error。
 * 进度条按「已完成批次」推进，避免几十秒的等待没有任何反馈；真正可渲染的报告
 * 在 done 事件里，直接赋值给 detail，不必再请求一次合同详情。
 *
 * @param {{ text?: string, focus?: string }} payload 为空时后端读取已上传文件
 */
async function startReview(payload = {}) {
  if (reviewing.value) return
  reviewing.value = true
  reviewWarnings.value = []
  reviewPercent.value = 3
  reviewStage.value = '正在读取合同文本…'

  let failure = ''
  try {
    await reviewContract(
      id,
      { save: true, text: payload.text || null, focus: payload.focus || null },
      {
        onEvent: ({ event, data }) => {
          if (event === 'meta') {
            reviewPercent.value = 6
            reviewStage.value = `已切分 ${data.clause_count} 个条款，分 ${data.batches} 批审查`
          } else if (event === 'precheck') {
            reviewPercent.value = 8
          } else if (event === 'stage') {
            reviewStage.value = data.message || '正在审查…'
            if (data.total) {
              const ratio = (data.batch - 1) / data.total
              reviewPercent.value = Math.max(
                reviewPercent.value,
                Math.round(8 + ratio * 86),
              )
            }
          } else if (event === 'progress') {
            if (data.total) {
              reviewPercent.value = Math.min(96, Math.round(8 + (data.batch / data.total) * 86))
            }
          } else if (event === 'warning') {
            reviewWarnings.value.push(data.detail)
          } else if (event === 'done') {
            reviewPercent.value = 100
            detail.value.ai_review_report = data.report
            detail.value.ai_review_at = data.reviewed_at
            if (data.saved) {
              ElMessage.success(`审查完成：${data.report.counts.total} 处风险，已保存`)
            } else {
              ElMessage.warning('审查完成，但报告未保存到合同台账')
            }
          } else if (event === 'error') {
            failure = data.detail || 'AI 审查失败'
          }
        },
      },
    )
    if (failure) ElMessage.error(failure)
  } catch (err) {
    ElMessage.error(err.message || 'AI 审查失败')
  } finally {
    reviewing.value = false
    reviewStage.value = ''
    reviewPercent.value = 0
  }
}

function submitTextReview() {
  const text = reviewText.value.trim()
  if (text.length < 50) {
    ElMessage.warning('合同正文过短，请粘贴完整正文')
    return
  }
  textVisible.value = false
  startReview({ text, focus: reviewFocus.value.trim() })
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
.contract-detail {
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

.review-progress {
  margin-bottom: 12px;
  padding: 12px 14px;
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  background: #fbfbfd;
}

.progress-text {
  display: inline-block;
  margin-top: 8px;
  font-size: 12px;
  color: var(--brand-muted);
}

.review-warning {
  margin-bottom: 8px;
}
</style>
