<template>
  <div class="ai-chat" :class="{ compact }">
    <!-- ============ 消息区 ============ -->
    <div ref="scrollRef" class="chat-scroll" @scroll="onScroll">
      <!-- 空态：引导问题 -->
      <div v-if="!messages.length" class="chat-empty">
        <div class="empty-badge">
          <el-icon :size="22"><MagicStick /></el-icon>
        </div>
        <h3>{{ restricted ? '有法律问题，先问一句' : 'AI 法律助手' }}</h3>
        <p class="empty-desc">
          {{
            restricted
              ? 'AI 会结合法律法规给出通俗解释，帮助你判断事情的性质和下一步该做什么。'
              : '基于本地法律知识库检索作答，回答会标注引用条文，点击编号可展开原文。'
          }}
        </p>

        <div class="samples">
          <button
            v-for="item in sampleList"
            :key="item"
            type="button"
            class="sample"
            @click="useSample(item)"
          >
            {{ item }}
          </button>
        </div>

        <div v-if="$slots.guide" class="guide-slot">
          <slot name="guide" />
        </div>

        <p class="empty-hint">
          {{
            restricted
              ? '如需针对本案的具体意见，请通过「在线留言」联系承办律师。'
              : '支持续接多轮追问；会话与引用记录会留存在「AI 法律助手」页面，可随时回看。'
          }}
        </p>
      </div>

      <!-- 消息列表 -->
      <div
        v-for="(m, index) in messages"
        :key="index"
        class="msg"
        :class="m.role"
      >
        <div class="avatar" :class="m.role === 'user' ? 'is-user' : 'is-ai'">
          <el-icon v-if="m.role === 'assistant'" :size="16"><MagicStick /></el-icon>
          <span v-else>{{ userInitial }}</span>
        </div>

        <div class="msg-main">
          <!-- 用户提问 -->
          <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.content }}</div>

          <!-- AI 回答 -->
          <template v-else>
            <div v-if="m.masked" class="mask-chip">
              <el-icon :size="12"><Lock /></el-icon>提问中的敏感信息已脱敏
            </div>

            <div class="bubble ai-bubble">
              <!-- 首 token 未到达：只显示阶段，不留空白 -->
              <div v-if="m.streaming && !m.content" class="thinking">
                <span class="dot" /><span class="dot" /><span class="dot" />
                <span class="thinking-text">{{ m.stage || '正在思考…' }}</span>
              </div>

              <div
                v-else
                class="markdown-body"
                @click="onCitationClick($event, m)"
                v-html="renderMarkdown(m.content)"
              />

              <span v-if="m.streaming && m.content" class="cursor">▍</span>

              <div v-if="m.warnings.length" class="msg-warnings">
                <div v-for="(w, wi) in m.warnings" :key="wi" class="warn-line">
                  <el-icon :size="12"><Warning /></el-icon>{{ w }}
                </div>
              </div>

              <div v-if="m.error" class="msg-error">
                <el-icon :size="13"><CircleClose /></el-icon>
                <span>{{ m.error }}</span>
                <el-button link type="primary" size="small" @click="retry(index)">重试</el-button>
              </div>

              <div v-else-if="m.interrupted" class="msg-interrupted">
                <el-icon :size="12"><VideoPause /></el-icon>已停止生成，以上内容不完整
              </div>
            </div>

            <!-- 引用列表 -->
            <div v-if="m.refs?.length" class="refs">
              <div class="refs-head">
                <span>引用条文 {{ m.refs.length }} 条</span>
                <span v-if="m.usedRefs?.length" class="used">回答中实际使用 {{ m.usedRefs.length }} 条</span>
              </div>
              <div class="ref-chips">
                <button
                  v-for="r in m.refs"
                  :key="r.index"
                  type="button"
                  class="ref-chip"
                  :class="{ used: isUsed(m, r) }"
                  :title="r.content ? r.content.slice(0, 120) : r.label"
                  @click="openRef(r)"
                >
                  <span class="chip-index">{{ r.index }}</span>
                  <span class="chip-label">{{ r.label }}</span>
                </button>
              </div>
            </div>

            <!-- 元信息 -->
            <div v-if="!m.streaming && m.content" class="msg-foot">
              <span v-if="m.elapsedMs">{{ (m.elapsedMs / 1000).toFixed(1) }}s</span>
              <span v-if="m.tokenUsage">约 {{ m.tokenUsage }} tokens</span>
              <button type="button" class="foot-btn" @click="copyText(m.content)">
                <el-icon :size="12"><CopyDocument /></el-icon>复制
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ============ 免责声明 ============ -->
    <div v-if="disclaimer" class="disclaimer-bar">
      <el-icon :size="12"><InfoFilled /></el-icon>{{ disclaimer }}
    </div>

    <!-- ============ 输入区 ============ -->
    <div class="composer">
      <el-input
        ref="inputRef"
        v-model="input"
        type="textarea"
        :autosize="{ minRows: 2, maxRows: 5 }"
        maxlength="1000"
        resize="none"
        :disabled="sending"
        :placeholder="placeholder || (restricted ? '描述你的情况，例如：借出去的钱要不回来…' : '输入法律问题，Enter 发送，Shift + Enter 换行')"
        class="composer-input"
        @keydown.enter.exact="onEnter"
      />

      <div class="composer-bar">
        <div class="composer-left">
          <el-select
            v-if="!restricted"
            v-model="source"
            size="small"
            class="source-select"
            :disabled="sending"
          >
            <el-option label="全部资料" value="" />
            <el-option label="仅法律条文" value="law" />
            <el-option label="仅律所知识" value="firm" />
          </el-select>
          <span v-if="!restricted" class="hint">回答会标注 [n] 引用，点击可展开条文</span>
        </div>

        <div class="composer-right">
          <span class="count">{{ input.length }}/1000</span>
          <el-button v-if="sending" size="small" plain @click="stop">
            <el-icon><VideoPause /></el-icon>停止
          </el-button>
          <el-button
            v-else
            type="primary"
            size="small"
            :disabled="!input.trim()"
            @click="send()"
          >
            <el-icon><Promotion /></el-icon>发送
          </el-button>
        </div>
      </div>
    </div>

    <LawRefDialog v-model="refVisible" :ref-data="activeRef" />
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  CircleClose,
  CopyDocument,
  InfoFilled,
  Lock,
  MagicStick,
  Promotion,
  VideoPause,
  Warning,
} from '@element-plus/icons-vue'
import { chat, getAiSession } from '@/api/ai'
import { renderMarkdown } from '@/utils/aiMarkdown'
import { useUserStore } from '@/stores/user'
import LawRefDialog from '@/components/LawRefDialog.vue'

const props = defineProps({
  sessionId: { type: Number, default: null },
  restricted: { type: Boolean, default: false },
  compact: { type: Boolean, default: false },
  prefill: { type: String, default: '' },
  prefillKey: { type: Number, default: 0 },
  placeholder: { type: String, default: '' },
})
const emit = defineEmits(['update:sessionId', 'session-created', 'finished'])

const userStore = useUserStore()
const scrollRef = ref(null)
const inputRef = ref(null)

const messages = ref([])
const input = ref('')
const source = ref('')
const sending = ref(false)
const stage = ref('')
const disclaimer = ref('')
const activeSessionId = ref(props.sessionId || null)
const pinned = ref(true)

const refVisible = ref(false)
const activeRef = ref(null)

let controller = null

const userInitial = computed(() => (userStore.realName || '我').slice(0, 1))

const STAFF_SAMPLES = [
  '违约金约定过高，法院一般如何调整？',
  '民间借贷只有转账记录、没有借条，能否起诉？',
  '劳动合同到期不续签，需要支付经济补偿吗？',
  '离婚时一方隐匿财产，另一方怎么救济？',
]

const CLIENT_SAMPLES = [
  '借给朋友的钱一直不还，我该怎么起诉？',
  '交通事故对方全责但不赔钱，怎么办？',
  '被人打伤，可以要求赔偿哪些项目？',
  '遗嘱自己写有效吗，需要公证吗？',
]

const sampleList = computed(() => (props.restricted ? CLIENT_SAMPLES : STAFF_SAMPLES))

/* ------------------------------------------------------------------ 滚动 */

function onScroll() {
  const el = scrollRef.value
  if (!el) return
  pinned.value = el.scrollHeight - el.scrollTop - el.clientHeight < 80
}

function scrollToBottom(force = false) {
  nextTick(() => {
    const el = scrollRef.value
    if (el && (force || pinned.value)) el.scrollTop = el.scrollHeight
  })
}

/* ------------------------------------------------------------------ 历史 */

function fromHistory(message) {
  return {
    role: message.role,
    content: message.content || '',
    refs: message.refs || [],
    usedRefs: [],
    warnings: [],
    stage: '',
    streaming: false,
    interrupted: false,
    error: '',
    elapsedMs: 0,
    tokenUsage: message.token_usage || 0,
  }
}

async function loadHistory(sessionId) {
  if (!sessionId) {
    messages.value = []
    return
  }
  try {
    const data = await getAiSession(sessionId, 'chat')
    messages.value = (data.messages || []).map(fromHistory)
    disclaimer.value = data.disclaimer || ''
    scrollToBottom(true)
  } catch {
    // 会话不存在或无权访问：清空即可，具体错误由请求拦截器提示
    messages.value = []
  }
}

/* --------------------------------------------------------------- 提问发送 */

function pushAssistant() {
  const message = {
    role: 'assistant',
    content: '',
    refs: [],
    usedRefs: [],
    warnings: [],
    stage: '',
    streaming: true,
    interrupted: false,
    error: '',
    masked: false,
    elapsedMs: 0,
    tokenUsage: 0,
  }
  messages.value.push(message)
  return message
}

async function send(text) {
  if (sending.value) return
  const question = (text ?? input.value).trim()
  if (question.length < 2) {
    ElMessage.warning('请把问题描述得再具体一点')
    return
  }

  input.value = ''
  sending.value = true
  stage.value = '正在检索法律条文…'
  pinned.value = true

  messages.value.push({
    role: 'user',
    content: question,
    refs: [],
    usedRefs: [],
    warnings: [],
  })
  const reply = pushAssistant()
  scrollToBottom(true)

  controller = new AbortController()
  try {
    await chat(
      {
        question,
        session_id: activeSessionId.value,
        source: source.value || null,
      },
      {
        signal: controller.signal,
        onEvent: ({ event, data }) => {
          if (event === 'meta') {
            if (data.session_id && data.session_id !== activeSessionId.value) {
              activeSessionId.value = data.session_id
              emit('update:sessionId', data.session_id)
              emit('session-created', { id: data.session_id, title: question.slice(0, 30) })
            }
            disclaimer.value = data.disclaimer || disclaimer.value
            reply.masked = !!data.masked
          } else if (event === 'stage') {
            stage.value = data.message || ''
            reply.stage = stage.value
          } else if (event === 'warning') {
            reply.warnings.push(data.detail)
          } else if (event === 'refs') {
            reply.refs = data.items || []
          } else if (event === 'delta') {
            reply.content += data.text || ''
            scrollToBottom()
          } else if (event === 'done') {
            reply.refs = data.refs || reply.refs
            reply.usedRefs = data.used_refs || []
            reply.tokenUsage = data.token_usage || 0
            reply.elapsedMs = data.elapsed_ms || 0
            reply.streaming = false
            if (data.disclaimer) disclaimer.value = data.disclaimer
            scrollToBottom()
            emit('finished', { sessionId: activeSessionId.value })
          } else if (event === 'error') {
            reply.error = data.detail || 'AI 服务暂时不可用'
            reply.streaming = false
          }
        },
      },
    )
  } catch (err) {
    if (err?.name === 'AbortError') {
      // 停止时若一个字都没生成，留一条「已停止」比留空气泡清楚
      if (reply.content) reply.interrupted = true
      else reply.error = '已停止生成'
    } else {
      reply.error = err?.message || '网络异常，请稍后重试'
    }
    reply.streaming = false
  } finally {
    sending.value = false
    stage.value = ''
    controller = null
  }
}

function stop() {
  controller?.abort()
}

function retry(index) {
  const target = messages.value[index]
  if (!target || sending.value) return
  // 找到这条回答对应的用户提问：连同失败的回答一起摘掉，再按原问题重发，
  // 否则消息列表里会留下两个一模一样的提问。
  for (let i = index - 1; i >= 0; i -= 1) {
    if (messages.value[i].role === 'user') {
      const question = messages.value[i].content
      messages.value.splice(i, 2)
      send(question)
      return
    }
  }
}

function useSample(text) {
  input.value = text
  nextTick(() => inputRef.value?.focus())
}

// 回车发送。中文输入法里按回车是「上屏」而不是「发送」，
// 必须看 isComposing（Safari/部分输入法只给 keyCode 229），否则会把拼音打出去。
function onEnter(event) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  send()
}

/* --------------------------------------------------------------- 引用弹层 */

function onCitationClick(event, message) {
  const el = event.target.closest?.('[data-cite]')
  if (!el) return
  const index = Number(el.dataset.cite)
  const hit = (message.refs || []).find((r) => Number(r.index) === index)
  if (!hit) {
    ElMessage.info(`第 ${index} 条引用不在本次检索结果中`)
    return
  }
  openRef(hit)
}

function openRef(refItem) {
  activeRef.value = refItem
  refVisible.value = true
}

function isUsed(message, refItem) {
  return (message.usedRefs || []).includes(Number(refItem.index))
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('回答已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}

/* ------------------------------------------------------------------ 生命周期 */

function newChat() {
  controller?.abort()
  activeSessionId.value = null
  messages.value = []
  input.value = ''
  disclaimer.value = ''
  emit('update:sessionId', null)
  nextTick(() => inputRef.value?.focus())
}

watch(
  () => props.sessionId,
  (val) => {
    if (val === activeSessionId.value) return
    // 切会话时先掐掉正在跑的流，否则旧回答会继续往新会话的界面上追加
    controller?.abort()
    activeSessionId.value = val || null
    loadHistory(val)
  },
  { immediate: true },
)

watch(
  () => [props.prefill, props.prefillKey],
  ([text]) => {
    if (!text) return
    input.value = text
    nextTick(() => inputRef.value?.focus())
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  controller?.abort()
})

defineExpose({ send, newChat, focusInput: () => inputRef.value?.focus(), stop })
</script>

<style scoped>
.ai-chat {
  display: flex;
  flex-direction: column;
  min-height: 0;
  height: 100%;
  background: #fff;
  border-radius: 12px;
}

/* ---------------- 消息区 ---------------- */
.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: 20px 22px 8px;
}

.chat-empty {
  max-width: 620px;
  margin: 6vh auto 0;
  text-align: center;
}

.empty-badge {
  width: 48px;
  height: 48px;
  margin: 0 auto 14px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-gold-deep);
  background: linear-gradient(135deg, rgba(201, 165, 92, 0.18), rgba(29, 43, 71, 0.06));
  border: 1px solid rgba(201, 165, 92, 0.3);
}

.chat-empty h3 {
  margin: 0 0 8px;
  font-size: 17px;
  color: var(--brand-ink);
}

.empty-desc {
  margin: 0 auto 18px;
  max-width: 480px;
  font-size: 13px;
  line-height: 1.8;
  color: var(--brand-muted);
}

.samples {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: center;
}

.sample {
  padding: 7px 13px;
  font-size: 13px;
  color: var(--brand-text);
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 18px;
  cursor: pointer;
  transition: all 0.15s;
}

.sample:hover {
  border-color: var(--brand-gold);
  color: var(--brand-gold-deep);
  background: rgba(201, 165, 92, 0.06);
}

.guide-slot {
  margin-top: 22px;
}

.empty-hint {
  margin: 18px auto 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--brand-muted);
}

/* ---------------- 单条消息 ---------------- */
.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  flex-shrink: 0;
  width: 32px;
  height: 32px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  font-weight: 600;
}

.avatar.is-ai {
  color: var(--brand-gold-light);
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
}

.avatar.is-user {
  color: #fff;
  background: linear-gradient(135deg, #59688a, #3d4a68);
}

.msg-main {
  min-width: 0;
  max-width: calc(100% - 90px);
}

.msg.user .msg-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble {
  padding: 12px 15px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.85;
}

.user-bubble {
  background: var(--brand-navy-soft);
  color: #fff;
  white-space: pre-wrap;
  border-top-right-radius: 4px;
}

.ai-bubble {
  background: #fcfcfd;
  border: 1px solid var(--brand-line);
  color: var(--brand-text);
  border-top-left-radius: 4px;
}

.mask-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--brand-gold-deep);
}

.thinking {
  display: flex;
  align-items: center;
  gap: 6px;
}

.thinking .dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--brand-gold);
  animation: bounce 1.2s infinite ease-in-out;
}

.thinking .dot:nth-child(2) {
  animation-delay: 0.15s;
}

.thinking .dot:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes bounce {
  0%,
  60%,
  100% {
    transform: translateY(0);
    opacity: 0.5;
  }
  30% {
    transform: translateY(-4px);
    opacity: 1;
  }
}

.thinking-text {
  margin-left: 4px;
  font-size: 12px;
  color: var(--brand-muted);
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

.msg-warnings {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px dashed var(--brand-line);
}

.warn-line {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: #b2761f;
  line-height: 1.7;
}

.msg-error {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  font-size: 12px;
  color: #c45656;
}

.msg-interrupted {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  font-size: 12px;
  color: var(--brand-muted);
}

/* ---------------- 引用 ---------------- */
.refs {
  margin-top: 10px;
  padding: 10px 12px;
  border-radius: 10px;
  background: rgba(244, 245, 248, 0.85);
  border: 1px solid var(--brand-line);
}

.refs-head {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 12px;
  color: var(--brand-muted);
  margin-bottom: 8px;
}

.refs-head .used {
  color: var(--brand-gold-deep);
}

.ref-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ref-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 4px 10px 4px 4px;
  font-size: 12px;
  color: var(--brand-text);
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.ref-chip:hover {
  border-color: var(--brand-gold);
  color: var(--brand-gold-deep);
}

.ref-chip.used {
  border-color: rgba(201, 165, 92, 0.55);
  background: rgba(201, 165, 92, 0.08);
}

.chip-index {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  font-size: 11px;
  color: var(--brand-gold-deep);
  background: rgba(201, 165, 92, 0.15);
}

.chip-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 220px;
}

/* ---------------- 元信息 ---------------- */
.msg-foot {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 6px;
  font-size: 11px;
  color: var(--brand-muted);
}

.foot-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0;
  font-size: 11px;
  color: var(--brand-muted);
  background: none;
  border: none;
  cursor: pointer;
}

.foot-btn:hover {
  color: var(--brand-gold-deep);
}

/* ---------------- 免责声明 ---------------- */
.disclaimer-bar {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 22px;
  font-size: 11.5px;
  color: var(--brand-muted);
  background: rgba(244, 245, 248, 0.7);
  border-top: 1px solid var(--brand-line);
}

/* ---------------- 输入区 ---------------- */
.composer {
  padding: 10px 16px 12px;
  border-top: 1px solid var(--brand-line);
  background: #fff;
  border-radius: 0 0 12px 12px;
}

.composer-input :deep(.el-textarea__inner) {
  border-radius: 10px;
  font-size: 14px;
  line-height: 1.7;
  padding: 10px 12px;
  box-shadow: none;
  border: 1px solid var(--brand-line);
  resize: none;
}

.composer-input :deep(.el-textarea__inner:focus) {
  border-color: var(--brand-gold);
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin-top: 8px;
}

.composer-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.source-select {
  width: 130px;
}

.hint {
  font-size: 11.5px;
  color: var(--brand-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.composer-right {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.count {
  font-size: 11.5px;
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

/* 抽屉里空间更窄，压缩留白 */
.compact .chat-scroll {
  padding: 14px 14px 6px;
}

.compact .msg-main {
  max-width: calc(100% - 60px);
}

.compact .disclaimer-bar {
  padding: 6px 14px;
}
</style>
