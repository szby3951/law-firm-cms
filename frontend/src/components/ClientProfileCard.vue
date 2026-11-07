<template>
  <el-card shadow="never" class="section profile-card" v-loading="loading">
    <template #header>
      <div class="card-head">
        <div class="head-left">
          <el-icon class="ai-icon"><UserFilled /></el-icon>
          <span>AI 客户画像</span>
          <el-tag v-if="generatedAt" size="small" effect="plain" type="info">
            {{ formatTime(generatedAt) }}
          </el-tag>
          <el-tag v-if="modelName" size="small" effect="plain" type="info">{{ modelName }}</el-tag>
        </div>
        <div class="head-actions">
          <el-button
            v-if="profile"
            link
            type="primary"
            :disabled="generating"
            @click="copyProfile"
          >
            <el-icon><CopyDocument /></el-icon>复制
          </el-button>
          <el-button type="primary" size="small" :loading="generating" @click="generate">
            <el-icon v-if="!generating"><Refresh /></el-icon>
            {{ generating ? '正在分析…' : profile ? '刷新画像' : '生成画像' }}
          </el-button>
        </div>
      </div>
    </template>

    <div class="toolbar">
      <el-input
        v-model="focus"
        class="focus-input"
        maxlength="300"
        clearable
        :disabled="generating"
        placeholder="可选：本次关注点，如「重点判断是否会流失」"
      />
      <span class="hint-text">基于档案、跟进、案件、合同、收费与沟通记录生成</span>
    </div>

    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      :closable="false"
      class="alert"
    />

    <div
      v-if="generating"
      v-loading="true"
      element-loading-text="正在聚合客户数据并生成画像，约需 15~30 秒…"
      class="loading-block"
    />

    <template v-else-if="profile">
      <div v-if="profile.tags?.length" class="tag-row">
        <el-tag
          v-for="tag in profile.tags"
          :key="tag"
          size="small"
          effect="light"
          type="warning"
          class="tag"
        >
          {{ tag }}
        </el-tag>
      </div>

      <div class="type-line">{{ profile.client_type }}</div>

      <div class="block">
        <div class="block-title">核心诉求</div>
        <p class="block-text">{{ profile.core_demands }}</p>
      </div>

      <div class="two-col">
        <div class="block">
          <div class="block-title">沟通偏好</div>
          <p class="block-text">{{ profile.communication || '数据不足' }}</p>
        </div>
        <div class="block">
          <div class="block-title">下一步跟进建议</div>
          <p class="block-text actions">{{ profile.next_actions || '数据不足' }}</p>
        </div>
      </div>

      <div class="block">
        <div class="block-title">
          风险点
          <span v-if="!profile.risks?.length" class="muted">未发现明显风险</span>
        </div>
        <div v-for="(risk, index) in profile.risks" :key="index" class="risk">
          <div class="risk-point">
            <span class="risk-index">{{ index + 1 }}</span>{{ risk.point }}
          </div>
          <div v-if="risk.basis" class="risk-row">
            <span class="risk-label">依据</span>{{ risk.basis }}
          </div>
          <div v-if="risk.action" class="risk-row">
            <span class="risk-label">应对</span>{{ risk.action }}
          </div>
        </div>
      </div>

      <el-collapse class="detail-collapse">
        <el-collapse-item
          :title="`判断依据（${profile.evidence?.length || 0} 条）与数据缺口（${profile.gaps?.length || 0} 项）`"
          name="detail"
        >
          <div v-if="profile.evidence?.length" class="detail-group">
            <div class="detail-title">数据依据</div>
            <div v-for="item in profile.evidence" :key="item" class="detail-item">· {{ item }}</div>
          </div>
          <div v-if="profile.gaps?.length" class="detail-group">
            <div class="detail-title">数据缺口（会影响判断准确性）</div>
            <div v-for="item in profile.gaps" :key="item" class="detail-item gap">· {{ item }}</div>
          </div>
          <div v-if="inputs?.skipped?.length" class="detail-group">
            <div class="detail-title">本次未纳入</div>
            <div v-for="item in inputs.skipped" :key="item" class="detail-item">{{ item }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div v-if="sourceChips.length" class="source-row">
        <span class="source-label">读取范围</span>
        <span v-for="chip in sourceChips" :key="chip" class="source-chip">{{ chip }}</span>
      </div>

      <p v-if="maskedSummary" class="mask-note">
        <el-icon><Lock /></el-icon>
        送入模型前已脱敏：{{ maskedSummary }}；数据库原文未改动。
      </p>
      <p v-if="disclaimer" class="disclaimer">{{ disclaimer }}</p>
    </template>

    <div v-else class="empty">
      <el-icon :size="26"><UserFilled /></el-icon>
      <p>
        AI 会读取该客户的档案、跟进记录、关联案件、合同、收费回款与沟通留言，
        生成「客户类型、核心诉求、风险点、沟通偏好、下一步跟进建议」，
        用于判断推进节奏、回款风险与流失可能。
      </p>
      <p class="hint">
        画像随客户存档，负责律师交接时可直接看到上一份判断；可随时刷新覆盖。
      </p>
    </div>
  </el-card>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CopyDocument,
  Lock,
  Refresh,
  UserFilled,
} from '@element-plus/icons-vue'
import { generateClientProfile, getClientProfile } from '@/api/clients'

const props = defineProps({
  clientId: { type: Number, required: true },
})

const loading = ref(false)
const generating = ref(false)
const focus = ref('')

const profile = ref(null)
const inputs = ref(null)
const generatedAt = ref('')
const modelName = ref('')
const disclaimer = ref('')
const errorText = ref('')

const maskedSummary = computed(() => inputs.value?.masked?.summary || '')

const sourceChips = computed(() => {
  const s = inputs.value?.stats
  if (!s) return []
  const chips = []
  if (s.follows != null) {
    const gap = s.days_since_follow != null ? `，${s.days_since_follow} 天前` : ''
    chips.push(`跟进 ${s.follows} 条${gap}`)
  }
  if (s.cases != null) chips.push(`案件 ${s.cases} 个（在办 ${s.active_cases || 0}）`)
  if (s.contracts) chips.push(`合同 ${s.contracts} 份`)
  if (s.messages != null) chips.push(`留言 ${s.messages} 条${s.unread ? `（未读 ${s.unread}）` : ''}`)
  if (s.fee_plans) {
    const unpaid = Number(s.unpaid_total || 0)
    chips.push(
      `收费 ${s.fee_plans} 份${unpaid > 0 ? `，未收 ¥${unpaid.toLocaleString('zh-CN', { minimumFractionDigits: 2 })}` : ''}${
        s.overdue_periods ? `，逾期 ${s.overdue_periods} 期` : ''
      }`,
    )
  }
  return chips
})

async function load() {
  loading.value = true
  try {
    const data = await getClientProfile(props.clientId)
    applyResult(data)
  } catch {
    // 未生成过时接口返回空画像；网络异常也不应阻断整页，生成时再提示
  } finally {
    loading.value = false
  }
}

function applyResult(data) {
  profile.value = data?.profile || null
  inputs.value = data?.inputs || null
  generatedAt.value = data?.ai_profile_at || ''
  modelName.value = data?.model || ''
  disclaimer.value = data?.disclaimer || ''
}

async function generate() {
  if (generating.value) return
  generating.value = true
  errorText.value = ''
  try {
    const data = await generateClientProfile(props.clientId, {
      focus: focus.value.trim() || null,
    })
    applyResult(data)
    ElMessage.success('客户画像已生成')
  } catch (err) {
    errorText.value = err.message || '画像生成失败，请稍后重试'
  } finally {
    generating.value = false
  }
}

async function copyProfile() {
  const p = profile.value
  if (!p) return
  const lines = [
    `客户类型：${p.client_type}`,
    `核心诉求：${p.core_demands}`,
    `沟通偏好：${p.communication}`,
    '风险点：',
    ...(p.risks || []).map(
      (r, i) => `${i + 1}. ${r.point}${r.basis ? `（依据：${r.basis}）` : ''}${r.action ? ` 应对：${r.action}` : ''}`,
    ),
    `下一步跟进建议：\n${p.next_actions}`,
    p.tags?.length ? `标签：${p.tags.join('、')}` : '',
  ].filter(Boolean)
  try {
    await navigator.clipboard.writeText(lines.join('\n'))
    ElMessage.success('画像已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<style scoped>
.profile-card {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.head-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.ai-icon {
  color: var(--brand-gold-deep);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}

.focus-input {
  flex: 1;
  min-width: 260px;
}

.hint-text {
  font-size: 12px;
  color: var(--brand-muted);
}

.alert {
  margin-bottom: 10px;
}

.loading-block {
  height: 160px;
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 10px;
}

.type-line {
  font-size: 17px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.6;
  padding-left: 10px;
  border-left: 3px solid var(--brand-gold);
  margin-bottom: 16px;
}

.block {
  margin-bottom: 16px;
}

.block-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-bottom: 6px;
  display: flex;
  align-items: baseline;
  gap: 8px;
}

.block-title .muted {
  font-weight: 400;
  font-size: 12px;
  color: var(--brand-muted);
}

.block-text {
  margin: 0;
  font-size: 14px;
  line-height: 1.85;
  color: var(--brand-text);
}

.block-text.actions {
  white-space: pre-line;
}

.two-col {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 20px;
}

@media (max-width: 900px) {
  .two-col {
    grid-template-columns: 1fr;
  }
}

.risk {
  border: 1px solid var(--brand-line);
  border-radius: 8px;
  padding: 10px 12px;
  margin-bottom: 8px;
  background: #fcfcfd;
}

.risk-point {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.6;
}

.risk-index {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 18px;
  height: 18px;
  margin-right: 8px;
  border-radius: 50%;
  background: #fdf1e6;
  color: #b0621f;
  font-size: 11px;
  font-weight: 600;
  vertical-align: 1px;
}

.risk-row {
  margin-top: 5px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--brand-text);
}

.risk-label {
  display: inline-block;
  min-width: 32px;
  margin-right: 8px;
  font-size: 11px;
  color: var(--brand-gold-deep);
}

.detail-collapse {
  margin-top: 4px;
  border-top: 1px solid var(--brand-line);
}

.detail-group {
  margin-bottom: 12px;
}

.detail-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-bottom: 5px;
}

.detail-item {
  font-size: 12px;
  line-height: 1.75;
  color: var(--brand-muted);
}

.detail-item.gap {
  color: #a5813d;
}

.source-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
}

.source-label {
  font-size: 12px;
  color: var(--brand-muted);
}

.source-chip {
  font-size: 12px;
  color: var(--brand-navy);
  background: var(--brand-navy-soft);
  padding: 2px 9px;
  border-radius: 10px;
}

.mask-note {
  display: flex;
  align-items: center;
  gap: 5px;
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--brand-muted);
}

.disclaimer {
  margin: 8px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--brand-muted);
}

.empty {
  text-align: center;
  color: var(--brand-muted);
  padding: 16px 12px 8px;
}

.empty p {
  max-width: 680px;
  margin: 6px auto;
  font-size: 13px;
  line-height: 1.75;
}

.empty .hint {
  font-size: 12px;
  opacity: 0.85;
}
</style>
