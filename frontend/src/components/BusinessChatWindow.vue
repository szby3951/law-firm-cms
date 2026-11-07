<template>
  <div class="biz-chat" :class="{ compact }">
    <!-- ============ 消息区 ============ -->
    <div ref="scrollRef" class="chat-scroll" @scroll="onScroll">
      <!-- 空态 -->
      <div v-if="!messages.length" class="chat-empty">
        <div class="empty-badge">
          <el-icon :size="22"><DataLine /></el-icon>
        </div>
        <h3>AI督办</h3>
        <p class="empty-desc">
          {{
            restricted
              ? '问一句你的案子办到哪了、还差多少钱、什么时候开庭；答案来自系统记录，快到期的事项会单独标出来。'
              : '问在办案件的进展、待收款、本周日程与合同到期；AI 按台账逐项核对，把逾期与临期事项挑出来。'
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
          这里只读业务数据，不解释法律条文；要问「法律怎么规定」，请到「AI 法律问答」。
        </p>
      </div>

      <!-- 消息列表 -->
      <div v-for="(m, index) in messages" :key="index" class="msg" :class="m.role">
        <div class="avatar" :class="m.role === 'user' ? 'is-user' : 'is-ai'">
          <el-icon v-if="m.role === 'assistant'" :size="16"><DataLine /></el-icon>
          <span v-else>{{ userInitial }}</span>
        </div>

        <div class="msg-main">
          <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.content }}</div>

          <template v-else>
            <div v-if="m.masked" class="mask-chip">
              <el-icon :size="12"><Lock /></el-icon>提问中的敏感信息已脱敏
            </div>

            <!-- 数据来源：先让用户看到"读了哪几条"，可点开核对 -->
            <div v-if="m.context?.items?.length" class="ctx-bar">
              <button
                type="button"
                class="ctx-head"
                @click="m.ctxExpanded = !m.ctxExpanded"
              >
                <el-icon :size="12"><DataLine /></el-icon>
                <span>已读取 {{ m.context.items.length }} 条业务数据</span>
                <span class="ctx-as">截至 {{ m.context.as_of }}</span>
                <el-icon :size="12" class="ctx-caret" :class="{ open: m.ctxExpanded }">
                  <ArrowDown />
                </el-icon>
              </button>
              <div v-if="m.ctxExpanded" class="ctx-chips">
                <button
                  v-for="(it, i) in m.context.items"
                  :key="i"
                  type="button"
                  class="ctx-chip"
                  :title="it.link ? '打开对应页面核对' : ''"
                  @click="goContext(it)"
                >
                  <span class="ctx-kind">{{ kindLabel(it.kind) }}</span>
                  <span class="ctx-label">{{ it.label }}</span>
                  <span v-if="it.detail" class="ctx-detail">{{ it.detail }}</span>
                </button>
                <span v-if="m.context.truncated" class="ctx-more">部分条目已省略</span>
              </div>
            </div>

            <div class="bubble ai-bubble">
              <div v-if="m.streaming && !m.content" class="thinking">
                <span class="dot" /><span class="dot" /><span class="dot" />
                <span class="thinking-text">{{ m.stage || '正在读取台账…' }}</span>
              </div>

              <div
                v-else
                class="markdown-body"
                v-html="renderMarkdown(m.content)"
              />

              <span v-if="m.streaming && m.content" class="cursor">▍</span>

              <div v-if="m.error" class="msg-error">
                <el-icon :size="13"><CircleClose /></el-icon>
                <span>{{ m.error }}</span>
                <el-button link type="primary" size="small" @click="retry(index)">
                  重试
                </el-button>
              </div>

              <div v-else-if="m.interrupted" class="msg-interrupted">
                <el-icon :size="12"><VideoPause /></el-icon>已停止生成，以上内容不完整
              </div>
            </div>

            <!-- 元信息：业务侧不展示 token 数，用户不关心；只留耗时与复制 -->
            <div v-if="!m.streaming && m.content" class="msg-foot">
              <span v-if="m.asOfText" class="as-of">数据截至 {{ m.asOfText }}</span>
              <span v-if="m.elapsedMs">{{ (m.elapsedMs / 1000).toFixed(1) }}s</span>
              <button type="button" class="foot-btn" @click="copyText(m.content)">
                <el-icon :size="12"><CopyDocument /></el-icon>复制
              </button>
            </div>
          </template>
        </div>
      </div>
    </div>

    <!-- ============ 数据口径提示 ============ -->
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
        maxlength="500"
        resize="none"
        :disabled="sending"
        :placeholder="
          placeholder ||
          (restricted
            ? '例如：我的案子办到哪一步了？我还差多少钱？'
            : '例如：这周有哪些开庭？还有哪些费用没收齐？')
        "
        class="composer-input"
        @keydown.enter.exact="onEnter"
      />

      <div class="composer-bar">
        <div class="composer-left">
          <span class="hint">只读取你权限内的案件、费用、日程与合同</span>
        </div>

        <div class="composer-right">
          <span class="count">{{ input.length }}/500</span>
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
            <el-icon><Promotion /></el-icon>查询
          </el-button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ArrowDown,
  CircleClose,
  CopyDocument,
  DataLine,
  InfoFilled,
  Lock,
  Promotion,
  VideoPause,
} from '@element-plus/icons-vue'
import { businessChat, getAiSession } from '@/api/ai'
import { renderMarkdown } from '@/utils/aiMarkdown'
import { useUserStore } from '@/stores/user'
import { useRouter } from 'vue-router'

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
const router = useRouter()
const scrollRef = ref(null)
const inputRef = ref(null)

const messages = ref([])
const input = ref('')
const sending = ref(false)
const disclaimer = ref('')
const activeSessionId = ref(props.sessionId || null)
const pinned = ref(true)

let controller = null

const userInitial = computed(() => (userStore.realName || '我').slice(0, 1))

const STAFF_SAMPLES = [
  '我手上的案子都办到哪一步了？',
  '还有哪些费用没收齐？',
  '这周有哪些开庭和期限？',
  '哪些合同快到期了？',
]

const CLIENT_SAMPLES = [
  '我的案子现在办到哪一步了？',
  '我一共要交多少钱，还差多少？',
  '下次开庭是什么时候？',
  '我的合同什么时候到期？',
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
    stage: '',
    streaming: false,
    interrupted: false,
    error: '',
    elapsedMs: 0,
    asOfText: '',
    // 历史里不存快照：那是当时的金额与进度，回看时展示会误导
    context: null,
    ctxExpanded: false,
  }
}

async function loadHistory(sessionId) {
  if (!sessionId) {
    messages.value = []
    return
  }
  try {
    const data = await getAiSession(sessionId, 'business')
    messages.value = (data.messages || []).map(fromHistory)
    disclaimer.value = data.disclaimer || ''
    scrollToBottom(true)
  } catch {
    messages.value = []
  }
}

/* --------------------------------------------------------------- 提问发送 */

function pushAssistant() {
  const message = {
    role: 'assistant',
    content: '',
    stage: '',
    streaming: true,
    interrupted: false,
    error: '',
    masked: false,
    elapsedMs: 0,
    asOfText: '',
    context: null,
    ctxExpanded: false,
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
  pinned.value = true

  messages.value.push({
    role: 'user',
    content: question,
  })
  const reply = pushAssistant()
  scrollToBottom(true)

  controller = new AbortController()
  try {
    await businessChat(
      { question, session_id: activeSessionId.value },
      {
        signal: controller.signal,
        onEvent: ({ event, data }) => {
          if (event === 'meta') {
            if (data.session_id && data.session_id !== activeSessionId.value) {
              activeSessionId.value = data.session_id
              emit('update:sessionId', data.session_id)
              emit('session-created', {
                id: data.session_id,
                title: question.slice(0, 30),
              })
            }
            disclaimer.value = data.disclaimer || disclaimer.value
            reply.masked = !!data.masked
          } else if (event === 'context') {
            reply.context = data
            // 业务查询的价值就在"读了哪几条"，默认展开，不像法律问答那样折叠
            reply.ctxExpanded = true
          } else if (event === 'stage') {
            reply.stage = data.message || ''
          } else if (event === 'delta') {
            reply.content += data.text || ''
            scrollToBottom()
          } else if (event === 'done') {
            reply.elapsedMs = data.elapsed_ms || 0
            reply.asOfText = data.as_of || reply.context?.as_of || ''
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
      if (reply.content) reply.interrupted = true
      else reply.error = '已停止生成'
    } else {
      reply.error = err?.message || '网络异常，请稍后重试'
    }
    reply.streaming = false
  } finally {
    sending.value = false
    controller = null
  }
}

function stop() {
  controller?.abort()
}

function retry(index) {
  const target = messages.value[index]
  if (!target || sending.value) return
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

function onEnter(event) {
  if (event.isComposing || event.keyCode === 229) return
  event.preventDefault()
  send()
}

/* ------------------------------------------------------------- 数据来源 */

const CTX_KIND_LABELS = {
  case: '案件',
  fee: '费用',
  schedule: '日程',
  contract: '合同',
  client: '客户',
}

function kindLabel(kind) {
  return CTX_KIND_LABELS[kind] || '记录'
}

function goContext(item) {
  if (!item?.link) {
    ElMessage.info('该条记录没有可跳转的页面')
    return
  }
  router.push(item.link)
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('已复制')
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
.biz-chat {
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
  line-height: 1.7;
  color: var(--brand-muted);
}

.samples {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.sample {
  padding: 6px 12px;
  font-size: 12.5px;
  color: var(--brand-text);
  background: #f7f8fa;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  cursor: pointer;
  transition: all 0.15s;
}

.sample:hover {
  color: var(--brand-gold-deep);
  border-color: rgba(201, 165, 92, 0.55);
  background: rgba(201, 165, 92, 0.06);
}

.guide-slot {
  margin-top: 18px;
}

.empty-hint {
  margin: 18px 0 0;
  font-size: 12px;
  color: var(--brand-muted);
}

/* ---------------- 消息 ---------------- */
.msg {
  display: flex;
  gap: 10px;
  margin-bottom: 18px;
}

.msg.user {
  flex-direction: row-reverse;
}

.avatar {
  flex: none;
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 600;
}

.avatar.is-ai {
  color: var(--brand-gold-deep);
  background: rgba(201, 165, 92, 0.14);
  border: 1px solid rgba(201, 165, 92, 0.28);
}

.avatar.is-user {
  color: #fff;
  background: var(--brand-navy);
}

.msg-main {
  min-width: 0;
  max-width: 78%;
}

.msg.user .msg-main {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
}

.bubble {
  padding: 10px 14px;
  font-size: 13.5px;
  line-height: 1.75;
  border-radius: 10px;
  word-break: break-word;
}

.user-bubble {
  color: #fff;
  background: var(--brand-navy);
  white-space: pre-wrap;
}

.ai-bubble {
  color: var(--brand-text);
  background: #f7f8fa;
  border: 1px solid var(--brand-line);
}

.mask-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-bottom: 6px;
  font-size: 11px;
  color: var(--brand-gold-deep);
}

/* ---------------- 数据来源 ---------------- */
.ctx-bar {
  margin-bottom: 6px;
}

.ctx-head {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px;
  font-size: 11px;
  color: var(--brand-muted);
  background: rgba(244, 245, 248, 0.9);
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.ctx-head:hover {
  color: var(--brand-gold-deep);
  border-color: rgba(201, 165, 92, 0.5);
}

.ctx-as {
  color: #9aa0ab;
}

.ctx-caret {
  transition: transform 0.2s;
}

.ctx-caret.open {
  transform: rotate(180deg);
}

.ctx-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}

.ctx-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 3px 10px;
  font-size: 11.5px;
  color: var(--brand-text);
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.ctx-chip:hover {
  border-color: var(--brand-gold);
  background: rgba(201, 165, 92, 0.06);
}

.ctx-kind {
  flex: none;
  padding: 0 5px;
  font-size: 10.5px;
  line-height: 16px;
  color: var(--brand-gold-deep);
  background: rgba(201, 165, 92, 0.14);
  border-radius: 4px;
}

.ctx-label {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 240px;
}

.ctx-detail {
  flex: none;
  color: var(--brand-muted);
}

.ctx-more {
  align-self: center;
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------------- 生成态 ---------------- */
.thinking {
  display: flex;
  align-items: center;
  gap: 5px;
  color: var(--brand-muted);
  font-size: 12.5px;
}

.dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: var(--brand-gold);
  animation: blink 1.2s infinite;
}

.dot:nth-child(2) {
  animation-delay: 0.2s;
}

.dot:nth-child(3) {
  animation-delay: 0.4s;
}

.thinking-text {
  margin-left: 4px;
}

@keyframes blink {
  0%,
  100% {
    opacity: 0.25;
  }
  50% {
    opacity: 1;
  }
}

.cursor {
  margin-left: 2px;
  color: var(--brand-gold);
  animation: blink 1s infinite;
}

.msg-error,
.msg-interrupted {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 8px;
  font-size: 12px;
  color: #c45656;
}

.msg-interrupted {
  color: var(--brand-muted);
}

.msg-foot {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  font-size: 11px;
  color: #9aa0ab;
}

.as-of {
  color: var(--brand-gold-deep);
}

.foot-btn {
  display: inline-flex;
  align-items: center;
  gap: 3px;
  padding: 0;
  font-size: 11px;
  color: #9aa0ab;
  background: none;
  border: none;
  cursor: pointer;
}

.foot-btn:hover {
  color: var(--brand-gold-deep);
}

/* ---------------- 底部 ---------------- */
.disclaimer-bar {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 6px 22px;
  font-size: 11px;
  color: var(--brand-muted);
  background: #fafbfc;
  border-top: 1px solid var(--brand-line);
}

.composer {
  padding: 12px 18px 14px;
  border-top: 1px solid var(--brand-line);
}

.composer-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}

.composer-left .hint {
  font-size: 11px;
  color: #9aa0ab;
}

.composer-right {
  display: flex;
  align-items: center;
  gap: 8px;
}

.count {
  font-size: 11px;
  color: #b6bbc4;
}

/* 正文排版在 src/styles/ai-markdown.css 里统一，这里只调字号 */
.markdown-body {
  font-size: 13.5px;
  line-height: 1.8;
}

.biz-chat.compact .chat-scroll {
  padding: 12px 14px 4px;
}

.biz-chat.compact .msg-main {
  max-width: 88%;
}
</style>
