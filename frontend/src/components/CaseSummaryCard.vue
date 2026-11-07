<template>
  <el-card shadow="never" class="section summary-card">
    <template #header>
      <div class="card-head">
        <div class="head-left">
          <el-icon class="ai-icon"><MagicStick /></el-icon>
          <span>AI 案件摘要</span>
          <el-tag v-if="generatedAt" size="small" effect="plain" type="info">
            {{ formatTime(generatedAt) }}
          </el-tag>
        </div>
        <div class="head-actions">
          <el-button v-if="content" link type="primary" :disabled="generating" @click="copySummary">
            <el-icon><CopyDocument /></el-icon>复制
          </el-button>
          <el-button type="primary" size="small" :loading="generating" @click="generate">
            <el-icon v-if="!generating"><Refresh /></el-icon>
            {{ generating ? '正在生成…' : content ? '重新生成' : '生成摘要' }}
          </el-button>
        </div>
      </div>
    </template>

    <div class="summary-toolbar">
      <el-input
        v-model="focus"
        class="focus-input"
        maxlength="300"
        clearable
        :disabled="generating"
        placeholder="可选：本次重点关注，如「仲裁时效与证据缺口」"
      />
      <el-tooltip
        content="关闭后只依据案件档案、时间线与日程，不读取文书/合同/附件"
        placement="top"
      >
        <el-switch v-model="includeMaterials" :disabled="generating" active-text="读取案卷材料" />
      </el-tooltip>
    </div>

    <el-alert
      v-if="errorText"
      :title="errorText"
      type="error"
      show-icon
      :closable="false"
      class="alert"
    />
    <el-alert
      v-for="(note, index) in warnings"
      :key="index"
      :title="note"
      type="warning"
      show-icon
      :closable="false"
      class="alert"
    />

    <!-- 首次等待首段 token：只显示进度，不留空白 -->
    <div
      v-if="generating && !streamText"
      v-loading="true"
      element-loading-text="正在读取案卷材料…"
      class="summary-loading"
    />

    <!-- 流式输出：纯文本 + 光标，结束后换成渲染好的 HTML -->
    <template v-else-if="generating && streamText">
      <div class="stage-line">{{ stage || '正在归纳案件要点…' }}</div>
      <div ref="bodyRef" class="summary-stream">{{ streamText }}<span class="cursor">▍</span></div>
    </template>

    <!-- 已有摘要（本次生成或历史） -->
    <template v-else-if="content">
      <div v-if="stats.length" class="summary-stats">
        <span v-for="item in stats" :key="item">{{ item }}</span>
      </div>
      <div ref="bodyRef" class="summary-content" v-html="contentHtml" />

      <el-collapse
        v-if="materials.length || skipped.length"
        class="materials"
      >
        <el-collapse-item
          :title="`本次读取的材料（${materials.length} 份${skipped.length ? `，未纳入 ${skipped.length} 项` : ''}）`"
          name="materials"
        >
          <div v-for="m in materials" :key="`${m.kind}-${m.title}`" class="material-row">
            <span class="kind">{{ m.kind_label }}</span>
            <span class="name" :title="m.title">{{ m.title }}</span>
            <span class="chars">
              {{ m.chars.toLocaleString('zh-CN') }} 字
              <template v-if="m.truncated"> · 节选 {{ m.included_chars.toLocaleString('zh-CN') }} 字</template>
            </span>
          </div>
          <div v-if="skipped.length" class="skipped">
            <div class="skipped-title">未纳入本次摘要：</div>
            <div v-for="item in skipped" :key="item" class="skipped-item">· {{ item }}</div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <p v-if="disclaimer" class="disclaimer">{{ disclaimer }}</p>
    </template>

    <!-- 空态 -->
    <div v-else class="summary-empty">
      <el-icon :size="26"><Document /></el-icon>
      <p>
        AI 会读取本案档案、时间线、待办日程，以及文书、合同、附件中可提取的文字，
        按「案件概况、争议焦点、事实与证据、有利与不利、下一步与期限、材料缺口」
        六节归纳，供交接与庭前准备使用。
      </p>
      <p class="hint">摘要按律师账号隔离，仅本人可见；每次生成都会留痕在 AI 会话中。</p>
    </div>
  </el-card>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument, Document, MagicStick, Refresh } from '@element-plus/icons-vue'
import { getCaseSummary, summarizeCase } from '@/api/ai'

const props = defineProps({
  caseId: { type: Number, required: true },
})

const generating = ref(false)
const focus = ref('')
const includeMaterials = ref(true)

const content = ref('')
const contentHtml = ref('')
const streamText = ref('')
const stage = ref('')
const warnings = ref([])
const errorText = ref('')
const generatedAt = ref('')
const disclaimer = ref('')
const materials = ref([])
const skipped = ref([])
const meta = ref(null)
const elapsedMs = ref(0)
const bodyRef = ref(null)

const stats = computed(() => {
  const list = []
  if (meta.value?.material_count != null) {
    list.push(`材料 ${meta.value.material_count} 份`)
    list.push(`${Number(meta.value.material_chars || 0).toLocaleString('zh-CN')} 字`)
  } else if (materials.value.length) {
    list.push(`材料 ${materials.value.length} 份`)
  }
  if (elapsedMs.value) list.push(`用时 ${(elapsedMs.value / 1000).toFixed(1)}s`)
  return list
})

async function loadHistory() {
  try {
    const data = await getCaseSummary(props.caseId)
    if (data?.content) {
      content.value = data.content
      contentHtml.value = data.html || ''
      generatedAt.value = data.generated_at || ''
      disclaimer.value = data.disclaimer || ''
    }
  } catch {
    // 没有历史摘要或权限不足时保持空态；真正的错误在生成时提示
  }
}

function scrollToBottom() {
  nextTick(() => {
    if (bodyRef.value) bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  })
}

async function generate() {
  if (generating.value) return
  generating.value = true
  streamText.value = ''
  content.value = ''
  contentHtml.value = ''
  warnings.value = []
  errorText.value = ''
  materials.value = []
  skipped.value = []
  meta.value = null
  elapsedMs.value = 0
  generatedAt.value = ''
  disclaimer.value = ''
  stage.value = '正在准备案件数据…'

  let failure = ''
  try {
    await summarizeCase(
      props.caseId,
      {
        focus: focus.value.trim() || null,
        include_materials: includeMaterials.value,
      },
      {
        onEvent: ({ event, data }) => {
          if (event === 'meta') {
            meta.value = data
            stage.value = `已读取 ${data.material_count} 份材料，共 ${Number(
              data.material_chars || 0,
            ).toLocaleString('zh-CN')} 字`
          } else if (event === 'context') {
            materials.value = data.materials || []
            skipped.value = data.skipped || []
          } else if (event === 'warning') {
            warnings.value.push(data.detail)
          } else if (event === 'stage') {
            stage.value = data.message || ''
          } else if (event === 'delta') {
            streamText.value += data.text || ''
            scrollToBottom()
          } else if (event === 'done') {
            content.value = data.content || ''
            contentHtml.value = data.html || ''
            generatedAt.value = data.generated_at || ''
            disclaimer.value = data.disclaimer || ''
            elapsedMs.value = data.elapsed_ms || 0
            materials.value = data.materials || materials.value
            streamText.value = ''
            stage.value = ''
            ElMessage.success('案件摘要已生成')
            nextTick(() => {
              if (bodyRef.value) bodyRef.value.scrollTop = 0
            })
          } else if (event === 'error') {
            failure = data.detail || '生成失败'
          }
        },
      },
    )
    if (failure) {
      errorText.value = failure
      ElMessage.error(failure)
    }
  } catch (err) {
    errorText.value = err.message || '案件摘要生成失败'
    ElMessage.error(errorText.value)
  } finally {
    generating.value = false
    stage.value = ''
  }
}

async function copySummary() {
  try {
    await navigator.clipboard.writeText(content.value)
    ElMessage.success('摘要已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}

onMounted(loadHistory)
</script>

<style scoped>
.summary-card {
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

.summary-toolbar {
  display: flex;
  align-items: center;
  gap: 14px;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.focus-input {
  flex: 1;
  min-width: 260px;
}

.alert {
  margin-bottom: 10px;
}

.summary-loading {
  height: 160px;
}

.stage-line {
  font-size: 12px;
  color: var(--brand-muted);
  margin-bottom: 8px;
}

.summary-stats {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.summary-stats span {
  font-size: 12px;
  color: var(--brand-muted);
  background: var(--brand-navy-soft);
  padding: 2px 9px;
  border-radius: 10px;
}

.summary-content,
.summary-stream {
  max-height: 560px;
  overflow-y: auto;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: #fcfcfd;
  padding: 16px 18px;
  font-size: 14px;
  line-height: 1.85;
  color: var(--brand-text);
}

.summary-stream {
  white-space: pre-wrap;
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
}

.cursor {
  color: var(--brand-gold-deep);
  animation: blink 1s steps(1) infinite;
}

@keyframes blink {
  50% {
    opacity: 0;
  }
}

.summary-content :deep(h2) {
  font-size: 16px;
  margin: 18px 0 8px;
  padding-left: 10px;
  border-left: 3px solid var(--brand-gold);
  color: var(--brand-ink);
}

.summary-content :deep(h2:first-child) {
  margin-top: 0;
}

.summary-content :deep(p) {
  margin: 0 0 8px;
}

.summary-content :deep(li) {
  margin-left: 18px;
  margin-bottom: 3px;
}

.summary-content :deep(blockquote) {
  margin: 0 0 12px;
  padding: 8px 12px;
  background: var(--brand-navy-soft);
  border-left: 3px solid var(--brand-navy);
  color: var(--brand-ink);
  border-radius: 0 6px 6px 0;
}

.summary-content :deep(strong) {
  color: var(--brand-ink);
}

.summary-empty {
  text-align: center;
  color: var(--brand-muted);
  padding: 16px 12px 8px;
}

.summary-empty p {
  max-width: 660px;
  margin: 6px auto;
  font-size: 13px;
  line-height: 1.75;
}

.summary-empty .hint {
  font-size: 12px;
  opacity: 0.85;
}

.materials {
  margin-top: 14px;
  border-top: none;
}

.material-row {
  display: flex;
  align-items: baseline;
  gap: 10px;
  padding: 5px 0;
  border-bottom: 1px dashed var(--brand-line);
  font-size: 12px;
}

.material-row .kind {
  flex: 0 0 72px;
  color: var(--brand-gold-deep);
}

.material-row .name {
  flex: 1;
  min-width: 0;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.material-row .chars {
  flex-shrink: 0;
  color: var(--brand-muted);
}

.skipped {
  margin-top: 10px;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.7;
}

.skipped-title {
  font-weight: 600;
  color: #a5813d;
  margin-bottom: 4px;
}

.disclaimer {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--brand-muted);
}
</style>
