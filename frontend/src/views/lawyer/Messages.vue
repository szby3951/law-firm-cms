<template>
  <div class="msg-page">
    <!-- ============ 概览 ============ -->
    <div class="stat-row">
      <div v-for="s in statCards" :key="s.label" class="stat-card">
        <div class="stat-icon" :style="{ background: s.bg, color: s.color }">
          <el-icon :size="20"><component :is="s.icon" /></el-icon>
        </div>
        <div class="stat-info">
          <div class="stat-value">{{ s.value }}</div>
          <div class="stat-label">{{ s.label }}</div>
        </div>
      </div>
    </div>

    <!-- ============ 双栏沟通 ============ -->
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="card-head">
          <div class="head-left">
            <span>客户留言</span>
            <span class="sub">
              共 {{ conversations.length }} 个会话 · {{ unreadTotal }} 条未读 ·
              回复后客户可在「在线留言」看到
            </span>
          </div>
          <div class="head-actions">
            <el-button plain :loading="loadingConv" @click="refreshAll">
              <el-icon><Refresh /></el-icon>刷新
            </el-button>
            <el-button plain :disabled="!unreadTotal" @click="readAll">
              <el-icon><Select /></el-icon>全部标为已读
            </el-button>
          </div>
        </div>
      </template>

      <div class="chat-body">
        <!-- 左：会话列表 -->
        <aside class="conv-panel">
          <div class="conv-tools">
            <el-input
              v-model="keyword"
              placeholder="搜索客户姓名"
              clearable
              @input="onKeyword"
              @clear="loadConversations"
            >
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>

            <el-radio-group
              v-model="filter"
              size="small"
              class="conv-filter"
              @change="loadConversations"
            >
              <el-radio-button value="all">全部会话</el-radio-button>
              <el-radio-button value="unread">
                未读<span v-if="unreadTotal" class="tab-count">{{ unreadTotal }}</span>
              </el-radio-button>
            </el-radio-group>
          </div>

          <el-scrollbar v-loading="loadingConv" class="conv-list">
            <el-empty
              v-if="!loadingConv && !conversations.length"
              :description="filter === 'unread' ? '没有未读会话' : '暂无客户留言'"
              :image-size="80"
            />

            <div
              v-for="c in conversations"
              :key="c.client_id"
              class="conv-item"
              :class="{ active: c.client_id === activeId }"
              @click="openConversation(c)"
            >
              <div class="avatar">{{ initials(c.client_name) }}</div>
              <div class="conv-main">
                <div class="conv-line1">
                  <span class="conv-name">{{ c.client_name || '未命名客户' }}</span>
                  <span class="conv-time">{{ relativeTime(c.last_at) }}</span>
                </div>
                <div class="conv-preview">
                  <span v-if="c.last_sender_role === 'lawyer'" class="me">我：</span>
                  <span v-else-if="c.last_sender_role === 'client'" class="peer">客户：</span>
                  {{ c.last_content || '（附件）' }}
                </div>
                <div class="conv-foot">
                  <span v-if="c.case_no" class="case-no">{{ c.case_no }}</span>
                  <span class="grow" />
                  <span class="total">{{ c.total }} 条</span>
                  <span v-if="c.unread" class="unread-pill">
                    {{ c.unread > 99 ? '99+' : c.unread }}
                  </span>
                </div>
              </div>
            </div>
          </el-scrollbar>
        </aside>

        <!-- 右：聊天窗口 -->
        <section v-if="activeId" class="chat-panel">
          <header class="chat-head">
            <div class="avatar-lg">{{ initials(header.client_name) }}</div>
            <div class="chat-title">
              <div class="line1">
                <span class="name">{{ header.client_name || '客户' }}</span>
                <template v-if="header.unread">
                  <el-tag type="danger" size="small" effect="light">
                    未读 {{ header.unread }}
                  </el-tag>
                  <el-button
                    link
                    type="primary"
                    size="small"
                    class="read-btn"
                    @click="markActiveRead()"
                  >
                    标为已读
                  </el-button>
                </template>
              </div>
              <div class="line2">
                <span v-if="header.case_no">案号 {{ header.case_no }} · </span>
                <span>共 {{ header.total }} 条留言</span>
              </div>
            </div>
            <div class="chat-actions">
              <el-button text @click="goClient">
                <el-icon><User /></el-icon>客户档案
              </el-button>
              <el-tooltip content="刷新本会话" placement="bottom">
                <el-button text circle :loading="loadingMsg" @click="loadMessages">
                  <el-icon><Refresh /></el-icon>
                </el-button>
              </el-tooltip>
            </div>
          </header>

          <el-scrollbar ref="scrollRef" v-loading="loadingMsg" class="chat-scroll">
            <div class="chat-stream">
              <div v-if="!loadingMsg && !messages.length" class="chat-empty">
                <el-empty description="还没有沟通记录，发出第一条留言吧" :image-size="90" />
              </div>

              <template v-for="item in timeline" :key="item.key">
                <div v-if="item.type === 'day'" class="day-divider">{{ item.label }}</div>
                <ChatMessage
                  v-else
                  :message="item.message"
                  :mine="item.message.sender_role === 'lawyer'"
                  :show-meta="item.showMeta"
                  :unread="!item.message.is_read && item.message.sender_role === 'client'"
                  :peer-name="header.client_name"
                  show-read-state
                  @preview="openPreview"
                />
              </template>
            </div>
          </el-scrollbar>

          <ChatComposer
            ref="composerRef"
            :loading="sending"
            placeholder="回复客户…（Ctrl / ⌘ + Enter 发送）"
            @send="handleSend"
          />
        </section>

        <section v-else class="chat-panel empty-panel">
          <div class="empty-wrap">
            <el-empty description="选择左侧客户，查看与他的全部沟通记录" :image-size="110" />
            <div class="empty-sub">客户从「在线留言」发来的消息会汇总到这里</div>
          </div>
        </section>
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
  watch,
} from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Refresh, Search, Select, User } from '@element-plus/icons-vue'
import {
  listConversations,
  listMessages,
  markAllRead,
  markConversationRead,
  sendMessage,
  uploadMessageAttachment,
} from '@/api/messages'
import { dateKey, isSameDay, relativeTime } from '@/utils/schedule'
import { dayLabel, initials } from '@/utils/message'
import ChatMessage from '@/components/ChatMessage.vue'
import ChatComposer from '@/components/ChatComposer.vue'
import AttachmentViewer from '@/components/AttachmentViewer.vue'

const route = useRoute()
const router = useRouter()

const base = computed(() => (route.path.startsWith('/admin') ? '/admin' : '/lawyer'))

const conversations = ref([])
const unreadTotal = ref(0)
const activeId = ref(null)
const messages = ref([])
const keyword = ref('')
const filter = ref('all')
const loadingConv = ref(false)
const loadingMsg = ref(false)
const sending = ref(false)
const scrollRef = ref(null)
const composerRef = ref(null)
const viewerVisible = ref(false)
const previewAtt = ref(null)

const header = reactive({
  client_name: '',
  lawyer_name: '',
  case_no: '',
  total: 0,
  unread: 0,
})

const stats = computed(() => ({
  total: conversations.value.length,
  unread: unreadTotal.value,
  waiting: conversations.value.filter((c) => c.last_sender_role === 'client').length,
  today: conversations.value.filter((c) => isSameDay(c.last_at, new Date())).length,
}))

const statCards = computed(() => [
  {
    label: '沟通会话',
    value: stats.value.total,
    icon: 'ChatDotRound',
    bg: '#eef1f7',
    color: 'var(--brand-navy)',
  },
  {
    label: '未读留言',
    value: stats.value.unread,
    icon: 'Bell',
    bg: '#fbeeea',
    color: '#a13f2f',
  },
  {
    label: '待我回复',
    value: stats.value.waiting,
    icon: 'EditPen',
    bg: '#f9f2e2',
    color: '#a5813d',
  },
  {
    label: '今日沟通',
    value: stats.value.today,
    icon: 'Calendar',
    bg: '#e8f4ef',
    color: '#1f5f4a',
  },
])

// 按日期分隔 + 同一发送人连续发言合并头像
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
      !prev ||
      prev.sender_role !== m.sender_role ||
      dateKey(prev.created_at) !== day
    out.push({ type: 'msg', key: `m-${m.id}`, message: m, showMeta })
  })
  return out
})

async function loadConversations() {
  loadingConv.value = true
  try {
    const params = {}
    if (keyword.value.trim()) params.keyword = keyword.value.trim()
    if (filter.value === 'unread') params.only_unread = true
    const data = await listConversations(params)
    conversations.value = data.items || []
    unreadTotal.value = data.unread || 0
    if (activeId.value == null && conversations.value.length) {
      activeId.value = conversations.value[0].client_id
      await loadMessages()
    }
  } finally {
    loadingConv.value = false
  }
}

async function loadMessages() {
  if (!activeId.value) return
  loadingMsg.value = true
  try {
    const data = await listMessages({
      client_id: activeId.value,
      page: 1,
      page_size: 100,
    })
    messages.value = data.items || []
    header.client_name = data.client_name || header.client_name
    header.lawyer_name = data.lawyer_name || ''
    header.total = data.total || messages.value.length
    header.unread = data.unread || 0

    const withCase = [...messages.value].reverse().find((m) => m.case_no)
    header.case_no = withCase?.case_no || ''

    // 打开会话不自动清红点：由律师点「标为已读」或回复时再清，
    // 这样列表与气泡上的未读标识能真实反映客户的新留言
    await scrollToBottom()
  } finally {
    loadingMsg.value = false
  }
}

async function openConversation(conv) {
  if (!conv?.client_id) return
  activeId.value = conv.client_id
  if (conv.client_name) header.client_name = conv.client_name
  await loadMessages()
}

async function refreshAll() {
  await loadConversations()
  if (activeId.value) await loadMessages()
}

async function readAll() {
  const res = await markAllRead()
  ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  await loadConversations()
  if (activeId.value) await loadMessages()
}

// 只清当前会话的红点；回复后也会静默调用一次
async function markActiveRead(showToast = true) {
  if (!activeId.value || !header.unread) {
    if (showToast) ElMessage.success('当前会话没有未读留言')
    return
  }
  const res = await markConversationRead(activeId.value)
  messages.value.forEach((m) => {
    if (m.sender_role === 'client') m.is_read = true
  })
  header.unread = 0
  if (showToast) ElMessage.success(`已标记 ${res.updated ?? 0} 条为已读`)
  await loadConversations()
}

async function handleSend({ content, files }) {
  if (!activeId.value) return
  sending.value = true
  try {
    const msg = await sendMessage({
      content: content || null,
      client_id: activeId.value,
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
    header.total = messages.value.length
    composerRef.value?.reset()

    if (failed) {
      ElMessage.warning(`留言已发送，${failed} 个附件上传失败，请重新发送附件`)
    } else {
      ElMessage.success(files.length ? '留言与附件已发送' : '留言已发送')
    }

    // 回复即视为已读，静默清掉本会话红点
    if (header.unread > 0) {
      messages.value.forEach((m) => {
        if (m.sender_role === 'client') m.is_read = true
      })
      header.unread = 0
      await markConversationRead(activeId.value)
    }

    await loadConversations()
    await scrollToBottom()
  } finally {
    sending.value = false
  }
}

async function scrollToBottom() {
  await nextTick()
  scrollRef.value?.setScrollTop?.(999999)
}

function onKeyword() {
  clearTimeout(kwTimer)
  kwTimer = setTimeout(() => loadConversations(), 320)
}

function goClient() {
  if (!activeId.value) return
  router.push(`${base.value}/clients/${activeId.value}`)
}

function openPreview(att) {
  previewAtt.value = att
  viewerVisible.value = true
}

let kwTimer = null
let pollTimer = null

watch(
  () => route.query.client_id,
  async (value) => {
    const id = Number(value || 0)
    if (!id || id === activeId.value) return
    activeId.value = id
    header.client_name = route.query.name ? String(route.query.name) : ''
    await loadMessages()
  },
)

onMounted(async () => {
  const qid = Number(route.query.client_id || 0)
  if (qid) {
    activeId.value = qid
    header.client_name = route.query.name ? String(route.query.name) : ''
  }
  // 无 query 时 loadConversations 会自动选中第一个会话并加载记录
  await loadConversations()
  if (qid && activeId.value) await loadMessages()

  pollTimer = setInterval(() => {
    if (!document.hidden) loadConversations()
  }, 60000)
})

onBeforeUnmount(() => {
  clearTimeout(kwTimer)
  clearInterval(pollTimer)
})
</script>

<style scoped>
.msg-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 概览卡 ---------- */
.stat-row {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 16px;
}

.stat-card {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 16px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.2;
}

.stat-label {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 4px;
}

/* ---------- 卡片头 ---------- */
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

.head-left {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-weight: 600;
  color: var(--brand-ink);
}

.head-left .sub {
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* ---------- 双栏 ---------- */
.chat-body {
  display: grid;
  grid-template-columns: 312px 1fr;
  height: calc(100vh - 268px);
  min-height: 540px;
}

.conv-panel {
  display: flex;
  flex-direction: column;
  min-height: 0;
  border-right: 1px solid var(--brand-line);
  background: #fff;
}

.conv-tools {
  padding: 12px 14px 10px;
  border-bottom: 1px solid var(--brand-line);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.conv-filter {
  width: 100%;
}

.conv-filter :deep(.el-radio-button) {
  flex: 1;
}

.conv-filter :deep(.el-radio-button__inner) {
  width: 100%;
  font-size: 12px;
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  color: var(--el-color-danger);
}

.conv-list {
  flex: 1;
  min-height: 0;
}

.conv-item {
  display: flex;
  gap: 10px;
  padding: 12px 14px;
  cursor: pointer;
  border-left: 3px solid transparent;
  transition: background-color 0.16s ease;
}

.conv-item:hover {
  background: #fafbfd;
}

.conv-item.active {
  background: #f5f7fb;
  border-left-color: var(--brand-gold);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-gold-deep);
  background: linear-gradient(135deg, #f4e7c8, #e6cf9c);
  border: 1px solid #e6d4ac;
}

.conv-main {
  flex: 1;
  min-width: 0;
}

.conv-line1 {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 8px;
}

.conv-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-time {
  font-size: 11px;
  color: var(--brand-muted);
  flex-shrink: 0;
}

.conv-preview {
  margin-top: 3px;
  font-size: 12px;
  color: var(--brand-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-preview .me {
  color: #5b6478;
}

.conv-preview .peer {
  color: var(--brand-gold-deep);
}

.conv-foot {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 5px;
}

.case-no {
  font-size: 10px;
  line-height: 15px;
  padding: 0 5px;
  border-radius: 3px;
  color: var(--brand-muted);
  background: #f2f4f8;
  letter-spacing: 0.3px;
  max-width: 130px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.conv-foot .grow {
  flex: 1;
}

.conv-foot .total {
  font-size: 11px;
  color: #b3b9c6;
}

.unread-pill {
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--el-color-danger);
  color: #fff;
  font-size: 11px;
  line-height: 18px;
  text-align: center;
}

/* ---------- 聊天窗口 ---------- */
.chat-panel {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  background: #fff;
}

.chat-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--brand-line);
  flex-shrink: 0;
}

.avatar-lg {
  width: 40px;
  height: 40px;
  border-radius: 11px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-gold-light);
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
}

.chat-title {
  flex: 1;
  min-width: 0;
}

.chat-title .line1 {
  display: flex;
  align-items: center;
  gap: 8px;
}

.chat-title .name {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
}

.chat-title .line2 {
  margin-top: 3px;
  font-size: 12px;
  color: var(--brand-muted);
}

.chat-title .read-btn {
  font-size: 12px;
  padding: 0;
  height: auto;
}

.chat-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.chat-actions :deep(.el-button) {
  font-size: 13px;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  background: #f7f8fb;
}

.chat-stream {
  padding: 18px 20px 10px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.chat-empty {
  padding: 26px 0;
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

.empty-panel {
  align-items: center;
  justify-content: center;
  background: #fafbfd;
}

.empty-wrap {
  text-align: center;
}

.empty-sub {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: -10px;
}

@media (max-width: 1200px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }

  .chat-body {
    grid-template-columns: 264px 1fr;
  }
}
</style>
