<template>
  <div class="client-detail" v-loading="loading">
    <!-- 返回 -->
    <div class="back-bar">
      <el-button link @click="$router.back()">
        <el-icon><ArrowLeft /></el-icon>返回客户列表
      </el-button>
    </div>

    <template v-if="client">
      <!-- 基本信息卡 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>基本信息</span>
            <div class="head-actions">
              <el-tag :type="statusMeta[client.status]?.type" effect="light" size="small">
                {{ statusMeta[client.status]?.label }}
              </el-tag>
              <el-button link type="primary" @click="goMessages">
                <el-icon><ChatDotRound /></el-icon>沟通留言
                <span v-if="msgUnread" class="msg-dot">{{ msgUnread }}</span>
              </el-button>
              <el-button link type="primary" @click="openEdit">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
            </div>
          </div>
        </template>

        <div class="profile-head">
          <div class="avatar">{{ client.name.slice(0, 1) }}</div>
          <div class="profile-title">
            <div class="name">
              {{ client.name }}
              <el-tag v-if="client.client_type === 'company'" size="small" effect="plain">机构</el-tag>
              <el-tag v-if="client.level === 'vip'" type="warning" size="small" effect="light">VIP</el-tag>
            </div>
            <div class="sub">
              {{ client.source_channel ? client.source_channel + ' · ' : '' }}创建于 {{ formatTime(client.created_at) }}
            </div>
          </div>
        </div>

        <el-descriptions :column="3" border class="desc">
          <el-descriptions-item label="联系电话">{{ client.phone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="证件号">{{ client.id_no || '—' }}</el-descriptions-item>
          <el-descriptions-item label="性别">{{ client.gender || '—' }}</el-descriptions-item>
          <el-descriptions-item label="来源渠道">{{ client.source_channel || '—' }}</el-descriptions-item>
          <el-descriptions-item label="客户分级">
            {{ client.level === 'vip' ? 'VIP' : '普通' }}
          </el-descriptions-item>
          <el-descriptions-item label="漏斗状态">
            {{ statusMeta[client.status]?.label }}
          </el-descriptions-item>
          <el-descriptions-item label="联系地址" :span="3">{{ client.address || '—' }}</el-descriptions-item>
          <el-descriptions-item label="备注" :span="3">{{ client.remark || '—' }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <!-- AI 客户画像（9.7）：律师/管理员可用，客户账号不展示 -->
      <ClientProfileCard :client-id="id" />

      <!-- 跟进记录 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>跟进记录</span>
            <el-button type="primary" size="small" @click="followVisible = true">
              <el-icon><Plus /></el-icon>添加跟进
            </el-button>
          </div>
        </template>

        <el-timeline v-if="follows.length">
          <el-timeline-item
            v-for="f in follows"
            :key="f.id"
            :timestamp="formatTime(f.created_at)"
            placement="top"
            :type="methodMeta[f.method]?.type"
          >
            <div class="follow-item">
              <div class="follow-meta">
                <el-tag size="small" effect="plain">{{ methodMeta[f.method]?.label }}</el-tag>
                <span v-if="f.next_follow_date" class="next">
                  下次跟进：{{ f.next_follow_date }}
                </span>
              </div>
              <div class="follow-content">{{ f.content }}</div>
            </div>
          </el-timeline-item>
        </el-timeline>
        <el-empty v-else description="暂无跟进记录" :image-size="80" />
      </el-card>

      <!-- 沟通留言 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>
              沟通留言
              <span v-if="msgUnread" class="unread-note">{{ msgUnread }} 条未读</span>
            </span>
            <el-button link type="primary" @click="goMessages">
              进入沟通<el-icon><ArrowRight /></el-icon>
            </el-button>
          </div>
        </template>

        <div v-if="recentMessages.length" class="msg-preview">
          <div v-for="m in recentMessages" :key="m.id" class="msg-line">
            <span class="role-pill" :class="m.sender_role">{{ m.sender_role_label }}</span>
            <span class="msg-text">{{ m.content || '（附件）' }}</span>
            <span class="msg-time">{{ formatTime(m.created_at) }}</span>
          </div>
        </div>
        <el-empty
          v-else
          description="还没有沟通记录，点「进入沟通」给客户留言"
          :image-size="70"
        />
      </el-card>

      <!-- 关联案件：按 client_id 拉取案件台账，律师仅见本人承办 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>
              关联案件
              <span v-if="caseTotal" class="count-note">{{ caseTotal }} 件</span>
            </span>
            <div class="head-actions">
              <el-button link type="primary" @click="goCaseList">
                去案件管理<el-icon><ArrowRight /></el-icon>
              </el-button>
              <el-button type="primary" size="small" @click="caseFormVisible = true">
                <el-icon><Plus /></el-icon>立案
              </el-button>
            </div>
          </div>
        </template>

        <!-- 首次加载用骨架，避免「暂无案件」在请求返回前闪一下 -->
        <el-skeleton v-if="caseLoading && !cases.length" :rows="3" animated />

        <el-table
          v-else-if="cases.length"
          :data="cases"
          v-loading="caseLoading"
          size="small"
          style="width: 100%"
        >
          <el-table-column prop="case_no" label="案号" width="140">
            <template #default="{ row }">
              <span class="case-no">{{ row.case_no }}</span>
            </template>
          </el-table-column>

          <el-table-column label="案件标题" min-width="200" show-overflow-tooltip>
            <template #default="{ row }">
              <el-button link type="primary" class="case-link" @click="goCase(row.id)">
                {{ row.title }}
              </el-button>
            </template>
          </el-table-column>

          <el-table-column prop="case_cause" label="案由" width="100">
            <template #default="{ row }">{{ row.case_cause || '—' }}</template>
          </el-table-column>

          <el-table-column label="主办律师" width="90">
            <template #default="{ row }">{{ row.lead_lawyer_name || '未分案' }}</template>
          </el-table-column>

          <el-table-column label="状态" width="88" align="center">
            <template #default="{ row }">
              <el-tag :type="caseStatusMeta[row.status]?.type" effect="light" size="small">
                {{ caseStatusMeta[row.status]?.label || row.status }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="标的额" width="110" align="right">
            <template #default="{ row }">
              <span class="amount">¥{{ formatAmount(row.amount) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="立案时间" width="130">
            <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
          </el-table-column>

          <el-table-column label="操作" width="70" align="center">
            <template #default="{ row }">
              <el-button link type="primary" @click="goCase(row.id)">详情</el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty v-else :description="emptyCaseText" :image-size="80" />

        <div v-if="caseTotal > cases.length" class="case-more">
          该客户案件较多，此处仅显示最近 {{ cases.length }} 件，完整台账请到
          <el-button link type="primary" @click="goCaseList">案件管理</el-button>
          查看。
        </div>
      </el-card>
    </template>

    <!-- 弹窗 -->
    <FollowDialog v-model="followVisible" :client-id="id" @saved="loadFollows" />
    <ClientForm v-model="editVisible" :client="client" @saved="load" />
    <CaseForm
      v-model="caseFormVisible"
      :client-id="id"
      :client-name="client?.name || ''"
      @saved="onCaseSaved"
    />
  </div>
</template>

<script setup>
import { computed, ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowLeft,
  ArrowRight,
  ChatDotRound,
  Edit,
  Plus,
} from '@element-plus/icons-vue'
import { getClient, listFollows } from '@/api/clients'
import { listCases } from '@/api/cases'
import { listMessages } from '@/api/messages'
import ClientProfileCard from '@/components/ClientProfileCard.vue'
import FollowDialog from './FollowDialog.vue'
import ClientForm from './ClientForm.vue'
import CaseForm from './CaseForm.vue'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)

// 同一页面在律师端与管理员端复用，跳转时走各自的基路径
const base = computed(() => (route.path.startsWith('/admin') ? '/admin' : '/lawyer'))
const isAdminView = computed(() => route.path.startsWith('/admin'))

const loading = ref(false)
const client = ref(null)
const follows = ref([])
const followVisible = ref(false)
const editVisible = ref(false)

// 关联案件
const cases = ref([])
const caseTotal = ref(0)
const caseLoading = ref(false)
const caseFormVisible = ref(false)

// 关联案件空态：律师端只看到本人承办的案件，文案需区分，避免误解为客户无案件
const emptyCaseText = computed(() =>
  isAdminView.value
    ? '该客户暂无委托案件，点「立案」为客户建档'
    : '该客户暂无您承办的案件（此处仅显示本人主办 / 协办的案件）',
)

// 沟通留言：最近 4 条预览 + 未读数
const recentMessages = ref([])
const msgUnread = ref(0)

const statusMeta = {
  potential: { label: '潜在', type: 'primary' },
  deal: { label: '成交', type: 'success' },
  lost: { label: '流失', type: 'info' },
}

// 案件状态（与案件台账保持一致）
const caseStatusMeta = {
  consulting: { label: '咨询中', type: 'primary' },
  filed: { label: '已立案', type: 'warning' },
  handling: { label: '办理中', type: 'success' },
  pending_close: { label: '待结案', type: 'info' },
  closed: { label: '已结案', type: 'success' },
  withdrawn: { label: '已退案', type: 'danger' },
}

const methodMeta = {
  phone: { label: '电话', type: 'primary' },
  wechat: { label: '微信', type: 'success' },
  visit: { label: '面访', type: 'warning' },
  email: { label: '邮件', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    client.value = await getClient(id)
  } finally {
    loading.value = false
  }
}

async function loadFollows() {
  follows.value = await listFollows(id)
}

// 该客户名下案件：后端按角色过滤（律师只见本人主办/协办，管理员见全部）
async function loadCases() {
  caseLoading.value = true
  try {
    const data = await listCases({ client_id: id, page: 1, page_size: 100 })
    cases.value = data.items || []
    caseTotal.value = data.total || 0
  } catch {
    // 案件接口异常不应影响客户基本信息展示
    cases.value = []
    caseTotal.value = 0
  } finally {
    caseLoading.value = false
  }
}

// 留言预览失败（例如客户尚未开通账号）不应影响整页加载
async function loadMessages() {
  try {
    const data = await listMessages({ client_id: id, page: 1, page_size: 4 })
    recentMessages.value = data.items || []
    msgUnread.value = data.unread || 0
  } catch {
    recentMessages.value = []
    msgUnread.value = 0
  }
}

function goMessages() {
  const query = { client_id: id }
  if (client.value?.name) query.name = client.value.name
  router.push({ path: `${base.value}/messages`, query })
}

function openEdit() {
  editVisible.value = true
}

function goCase(caseId) {
  router.push(`${base.value}/cases/${caseId}`)
}

// 跳案件台账并带上客户筛选，案件列表会据此过滤
function goCaseList() {
  const query = { client_id: id }
  if (client.value?.name) query.client_name = client.value.name
  router.push({ path: `${base.value}/cases`, query })
}

function onCaseSaved() {
  loadCases()
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

function formatAmount(v) {
  if (v === null || v === undefined) return '0'
  return Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

onMounted(() => {
  load()
  loadFollows()
  loadMessages()
  loadCases()
})
</script>

<style scoped>
.client-detail {
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

.profile-head {
  display: flex;
  align-items: center;
  gap: 16px;
  margin-bottom: 20px;
}

.profile-head .avatar {
  width: 56px;
  height: 56px;
  border-radius: 12px;
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
  color: var(--brand-gold-light);
  font-size: 22px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.profile-title .name {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
  display: flex;
  align-items: center;
  gap: 8px;
}

.profile-title .sub {
  font-size: 13px;
  color: var(--brand-muted);
  margin-top: 6px;
}

.desc {
  margin-top: 4px;
}

.follow-item {
  padding: 4px 0;
}

.follow-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 6px;
}

.follow-meta .next {
  font-size: 12px;
  color: var(--brand-gold-deep);
}

.follow-content {
  font-size: 14px;
  color: var(--brand-text);
  line-height: 1.7;
  white-space: pre-wrap;
}

/* ---------- 沟通留言 ---------- */
.msg-dot {
  margin-left: 4px;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--el-color-danger);
  color: #fff;
  font-size: 10px;
  line-height: 16px;
  text-align: center;
}

.unread-note {
  margin-left: 8px;
  font-size: 11px;
  font-weight: 400;
  color: var(--el-color-danger);
}

.msg-preview {
  display: flex;
  flex-direction: column;
}

.msg-line {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 0;
  border-bottom: 1px dashed var(--brand-line);
}

.msg-line:first-child {
  padding-top: 0;
}

.msg-line:last-child {
  padding-bottom: 0;
  border-bottom: none;
}

.role-pill {
  flex-shrink: 0;
  font-size: 11px;
  line-height: 18px;
  padding: 0 7px;
  border-radius: 4px;
  background: #eef1f7;
  color: var(--brand-navy);
}

.role-pill.client {
  background: #fdf8ec;
  color: var(--brand-gold-deep);
  border: 1px solid #e6d4ac;
  line-height: 16px;
}

.msg-text {
  flex: 1;
  min-width: 0;
  font-size: 13px;
  color: var(--brand-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.msg-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------- 关联案件 ---------- */
.count-note {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.case-no {
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12px;
  color: var(--brand-navy-soft);
}

.case-link {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: bottom;
}

.amount {
  font-weight: 600;
  color: var(--brand-gold-deep);
}

.case-more {
  margin-top: 12px;
  font-size: 12px;
  color: var(--brand-muted);
}
</style>
