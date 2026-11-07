<template>
  <div class="client-msg">
    <!-- ============ 概览 ============ -->
    <div class="summary">
      <div class="summary-left">
        <div class="summary-icon">
          <el-icon :size="22"><ChatDotRound /></el-icon>
        </div>
        <div>
          <div class="summary-title">在线留言</div>
          <div class="summary-sub">
            与承办律师直接沟通，材料可随留言上传 · 共 {{ total }} 条消息<span v-if="unread">
              ，{{ unread }} 条未读</span>
          </div>
        </div>
      </div>
      <div class="summary-actions">
        <el-button plain class="light-btn" :disabled="!unread" @click="readAll">
          <el-icon><Select /></el-icon>全部标为已读
        </el-button>
        <el-button plain class="light-btn" :loading="loadingMsg" @click="refresh">
          <el-icon><Refresh /></el-icon>刷新
        </el-button>
      </div>
    </div>

    <!-- ============ 聊天 ============ -->
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="card-head">
          <div class="who">
            <div class="avatar">{{ initials(lawyerName) }}</div>
            <div class="who-text">
              <div class="name">
                {{ lawyerName }}
                <el-tag size="small" effect="plain" class="role-tag">承办律师</el-tag>
              </div>
              <div class="sub">{{ lawyerSub }}</div>
            </div>
          </div>

          <div class="head-actions">
            <el-radio-group
              v-if="conversations.length > 1"
              :model-value="activeLawyer"
              size="small"
              @change="switchLawyer"
            >
              <el-radio-button
                v-for="c in conversations"
                :key="c.lawyer_id"
                :value="c.lawyer_id"
              >
                {{ c.lawyer_name }}
                <span v-if="c.unread" class="tab-count">{{ c.unread }}</span>
              </el-radio-button>
            </el-radio-group>
            <span v-else class="privacy">
              <el-icon><Lock /></el-icon>仅您与律师可见
            </span>
          </div>
        </div>
      </template>

      <div class="chat-body">
        <el-scrollbar ref="scrollRef" v-loading="loadingMsg" class="chat-scroll">
          <div class="chat-stream">
            <div v-if="!loadingMsg && !messages.length" class="welcome">
              <div class="welcome-icon">
                <el-icon :size="28"><ChatLineRound /></el-icon>
              </div>
              <div class="welcome-title">还没有沟通记录</div>
              <div class="welcome-sub">
                案件进展有疑问、需要补充材料，都可以直接给律师留言，回复会显示在这里
              </div>
            </div>

            <template v-for="item in timeline" :key="item.key">
              <div v-if="item.type === 'day'" class="day-divider">{{ item.label }}</div>
              <ChatMessage
                v-else
                :message="item.message"
                :mine="item.message.sender_role === 'client'"
                :show-meta="item.showMeta"
                :peer-name="lawyerName"
                @preview="openPreview"
              />
            </template>
          </div>
        </el-scrollbar>

        <ChatComposer
          ref="composerRef"
          :loading="sending"
          placeholder="给律师留言…（可上传图片、PDF 等材料）"
          @send="handleSend"
        />
      </div>
    </el-card>

    <AttachmentViewer v-model="viewerVisible" :attachment="previewAtt" />
  </div>
</template>

<script setup>
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  reactive,
  ref,
} from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ChatDotRound, Lock, Refresh, Select } from '@element-plus/icons-vue'
import {
  listConversations,
  listMyMessages,
  markMyAllRead,
  sendMessage,
  uploadMessageAttachment,
} from '@/api/messages'
import { dateKey, relativeTime } from '@/utils/schedule'
import { dayLabel, initials } from '@/utils/message'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatComposer from '@/components/ChatComposer.vue'
import AttachmentViewer from '@/components/AttachmentViewer.vue'

const route = useRoute()

const conversations = ref([])
const activeLawyer = ref(null)
const messages = ref([])
const unread = ref(0)
const total = ref(0)
const loadingMsg = ref(false)
const sending = ref(false)
const scrollRef = ref(null)
const composerRef = ref(null)
const viewerVisible = ref(false)
const previewAtt = ref(null)

const header = reactive({ lawyer_name: '', total: 0 })

const lawyerName = computed(
  () =>
    header.lawyer_name ||
    conversations.value.find((c) => c.lawyer_id === activeLawyer.value)?.lawyer_name ||
    '承办律师',
)

const lawyerSub = computed(() => {
  if (!messages.value.length) return '有疑问或需要补充材料，直接在这里留言'
  const last = messages.value[messages.value.length - 1]
  return `共 ${messages.value.length} 条消息 · 最近沟通 ${relativeTime(last.created_at)}`
})

const timeline = computed(() => {
  const out = []
  let lastDay = ''
  messages.value.forEach((m, i) => {
    const day = dateKey(m.created_at)
    if (day !== lastDay) {
      out.push({ type: 'day', key: `day-${day}-${i}`, label: dayLabel(m.created_at) })
      lastDay = day
    }
    const prev = messages.value[i - 1]
    const showMeta =
      !prev || prev.sender_role !== m.sender_role || dateKey(prev.created_at) !== day
    out.push({ type: 'msg', key: `m-${m.id}`, message: m, showMeta })
  })
  return out
})

async function loadConversations() {
  const data = await listConversations()
  conversations.value = data.items || []
  unread.value = data.unread || 0
  total.value = conversations.value.reduce((sum, c) => sum + (c.total || 0), 0)

  if (activeLawyer.value == null) {
    const firstUnread = conversations.value.find((c) => c.unread > 0)
    activeLawyer.value = firstUnread?.lawyer_id ?? conversations.value[0]?.lawyer_id ?? null
  }
}

async function loadMessages({ silent = false } = {}) {
  const atBottom = isNearBottom()
  if (!silent) loadingMsg.value = true
  try {
    const data = await listMyMessages({
      lawyer_id: activeLawyer.value || undefined,
      page: 1,
      page_size: 100,
    })
    messages.value = data.items || []
    header.lawyer_name = data.lawyer_name || header.lawyer_name
    header.total = data.total || 0

    if (data.unread > 0) {
      await markMyAllRead()
      messages.value.forEach((m) => {
        if (m.sender_role === 'lawyer') m.is_read = true
      })
      await loadConversations()
    }

    if (!silent || atBottom) await scrollToBottom()
  } finally {
    if (!silent) loadingMsg.value = false
  }
}

function isNearBottom() {
  const wrap = scrollRef.value?.wrapRef
  if (!wrap) return true
  return wrap.scrollTop + wrap.clientHeight >= wrap.scrollHeight - 60
}

async function scrollToBottom() {
  await nextTick()
  scrollRef.value?.setScrollTop?.(999999)
}

async function refresh() {
  await loadConversations()
  await loadMessages()
}

async function switchLawyer(value) {
  activeLawyer.value = value
  await loadMessages()
}

async function readAll() {
  const res = await markMyAllRead()
  ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  await loadConversations()
  await loadMessages({ silent: true })
}

async function handleSend({ content, files }) {
  sending.value = true
  try {
    const msg = await sendMessage({
      content: content || null,
      lawyer_id: activeLawyer.value || undefined,
    })

    const uploaded = []
    let failed = 0
    for (const f of files) {
      try {
        const att = await uploadMessageAttachment(msg.id, f.file)
        uploaded.push(att)
      } catch {
        failed += 1
      }
    }
    msg.attachments = uploaded
    messages.value.push(msg)
    if (!activeLawyer.value && msg.lawyer_id) activeLawyer.value = msg.lawyer_id
    composerRef.value?.reset()

    if (failed) {
      ElMessage.warning(`留言已发送，${failed} 个附件上传失败，请重新发送附件`)
    } else {
      ElMessage.success(files.length ? '留言与材料已发送' : '留言已发送')
    }

    await loadConversations()
    await scrollToBottom()
  } finally {
    sending.value = false
  }
}

function openPreview(att) {
  previewAtt.value = att
  viewerVisible.value = true
}

let pollTimer = null

onMounted(async () => {
  await loadConversations()
  await loadMessages()

  pollTimer = setInterval(async () => {
    if (document.hidden) return
    try {
      await loadConversations()
      await loadMessages({ silent: true })
    } catch {
      // 轮询失败静默，等下一次
    }
  }, 60000)
})

onBeforeUnmount(() => clearInterval(pollTimer))
</script>

<style scoped>
.client-msg {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 概览 ---------- */
.summary {
  background: linear-gradient(
    135deg,
    var(--brand-navy-soft) 0%,
    var(--brand-navy) 60%,
    var(--brand-navy-deep) 100%
  );
  border-radius: 12px;
  padding: 20px 24px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  color: #fff;
}

.summary-left {
  display: flex;
  align-items: center;
  gap: 14px;
}

.summary-icon {
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: rgba(255, 255, 255, 0.12);
  color: var(--brand-gold-light);
  display: flex;
  align-items: center;
  justify-content: center;
}

.summary-title {
  font-size: 17px;
  font-weight: 600;
  letter-spacing: 1px;
}

.summary-sub {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.62);
}

.summary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.light-btn {
  background: rgba(255, 255, 255, 0.08);
  border-color: rgba(255, 255, 255, 0.24);
  color: #f2f4f8;
}

.light-btn:hover,
.light-btn:focus {
  background: rgba(255, 255, 255, 0.16);
  border-color: var(--brand-gold-light);
  color: #fff;
}

.light-btn.is-disabled,
.light-btn.is-disabled:hover {
  background: rgba(255, 255, 255, 0.04);
  border-color: rgba(255, 255, 255, 0.12);
  color: rgba(255, 255, 255, 0.38);
}

/* ---------- 聊天卡片 ---------- */
.chat-card {
  border-radius: 12px;
  overflow: hidden;
}

.chat-card :deep(.el-card__body) {
  padding: 0;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.who {
  display: flex;
  align-items: center;
  gap: 12px;
}

.avatar {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-gold-light);
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
  flex-shrink: 0;
}

.who-text .name {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
}

.role-tag {
  font-weight: 400;
  color: var(--brand-gold-deep);
  border-color: #e6d4ac;
  background: #fdf8ec;
}

.who-text .sub {
  margin-top: 4px;
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.privacy {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: var(--el-color-danger);
}

/* ---------- 聊天主体 ---------- */
.chat-body {
  display: flex;
  flex-direction: column;
  height: calc(100vh - 250px);
  min-height: 520px;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  background: #f7f8fb;
}

.chat-stream {
  padding: 20px 24px 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.welcome {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
  padding: 60px 20px;
  text-align: center;
}

.welcome-icon {
  width: 54px;
  height: 54px;
  border-radius: 14px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-gold-deep);
  background: linear-gradient(135deg, #fdf8ec, #f6ecd4);
  border: 1px solid #e6d4ac;
}

.welcome-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-top: 4px;
}

.welcome-sub {
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.8;
  max-width: 380px;
}

.day-divider {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 11px;
  color: var(--brand-muted);
  margin: 4px 0;
}

.day-divider::before,
.day-divider::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--brand-line);
}

@media (max-width: 900px) {
  .summary {
    flex-direction: column;
    align-items: flex-start;
  }

  .chat-stream {
    padding: 16px 14px 10px;
  }
}
</style>
