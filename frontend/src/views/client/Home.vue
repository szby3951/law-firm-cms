<template>
  <div class="home">
    <!-- 欢迎条 -->
    <div class="hero">
      <div class="hero-main">
        <div class="hero-greet">{{ greeting }}，{{ userStore.realName }}</div>
        <p class="hero-sub">您的委托事务进展，我们会及时同步给您</p>
      </div>
      <div class="hero-badge">委托人</div>
    </div>

    <!-- 指标卡 -->
    <StatCards :items="stats" :columns="3" :loading="loading" />

    <!-- 最近案件 -->
    <el-card shadow="never" class="block">
      <template #header>
        <div class="block-head">
          <span>最近案件</span>
          <el-button link type="primary" @click="go('/client/cases')">
            全部案件
            <el-icon class="arrow"><ArrowRight /></el-icon>
          </el-button>
        </div>
      </template>

      <el-table :data="recentCases" v-loading="loading" style="width: 100%">
        <el-table-column prop="case_no" label="案号" width="150">
          <template #default="{ row }">
            <span class="case-no">{{ row.case_no }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="title" label="案件标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="case_cause" label="案由" min-width="110">
          <template #default="{ row }">{{ row.case_cause || '—' }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type" effect="light" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="立案时间" width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="96" align="center" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="go(`/client/cases/${row.id}`)">进度</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty
        v-if="!loading && !recentCases.length"
        description="暂无委托案件，律师立案后会在这里显示"
        :image-size="88"
      />
    </el-card>

    <!-- 快捷入口 -->
    <div class="shortcuts">
      <div v-for="s in shortcuts" :key="s.path" class="sc" @click="go(s.path)">
        <div class="sc-icon">
          <el-icon :size="18"><component :is="s.icon" /></el-icon>
        </div>
        <div class="sc-text">
          <div class="sc-title">{{ s.title }}</div>
          <div class="sc-desc">{{ s.desc }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowRight } from '@element-plus/icons-vue'
import { listMyCases } from '@/api/cases'
import { listMyBills } from '@/api/billing'
import { getMyUnreadCount as getNotifyUnread } from '@/api/notifications'
import { getMyUnreadCount as getMessageUnread } from '@/api/messages'
import { useUserStore } from '@/stores/user'
import StatCards from '@/components/StatCards.vue'

const router = useRouter()
const userStore = useUserStore()

const loading = ref(false)
const cases = ref([])
const bills = ref([])
const notifyUnread = ref(0)
const messageUnread = ref(0)

// 与列表页保持一致的案件状态口径
const statusMeta = {
  consulting: { label: '咨询中', type: 'primary' },
  filed: { label: '已立案', type: 'warning' },
  handling: { label: '办理中', type: 'success' },
  pending_close: { label: '待结案', type: 'info' },
  closed: { label: '已结案', type: 'success' },
  withdrawn: { label: '已退案', type: 'danger' },
}

const ACTIVE_STATUSES = ['consulting', 'filed', 'handling', 'pending_close']

const greeting = computed(() => {
  const h = new Date().getHours()
  if (h < 12) return '上午好'
  if (h < 18) return '下午好'
  return '晚上好'
})

const activeCount = computed(
  () => cases.value.filter((c) => ACTIVE_STATUSES.includes(c.status)).length
)

const unpaidTotal = computed(() =>
  bills.value.reduce((sum, b) => sum + Number(b.unpaid_amount || 0), 0)
)

const unpaidPeriods = computed(
  () => bills.value.filter((b) => Number(b.unpaid_amount || 0) > 0).length
)

const totalUnread = computed(() => notifyUnread.value + messageUnread.value)

const stats = computed(() => [
  {
    label: '在办案件',
    value: activeCount.value,
    unit: '件',
    tone: 'navy',
    hint: `累计委托 ${cases.value.length} 件`,
  },
  {
    label: '待缴费用',
    value: `¥${unpaidTotal.value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`,
    tone: 'gold',
    hint: unpaidPeriods.value ? `${unpaidPeriods.value} 期未结清` : '暂无待缴账单',
  },
  {
    label: '未读提醒',
    value: totalUnread.value,
    unit: '条',
    tone: totalUnread.value ? 'rose' : 'slate',
    hint: `通知 ${notifyUnread.value} · 留言 ${messageUnread.value}`,
  },
])

// 只展示最近 5 条，完整列表在「我的案件」页
const recentCases = computed(() =>
  [...cases.value]
    .sort((a, b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, 5)
)

const shortcuts = [
  { path: '/client/contracts', title: '我的合同', desc: '合同文本与签署状态', icon: 'Tickets' },
  { path: '/client/bills', title: '我的账单', desc: '应收 · 已缴 · 发票', icon: 'Money' },
  { path: '/client/documents', title: '我的文书', desc: '律师发布的文书', icon: 'Document' },
  { path: '/client/messages', title: '在线留言', desc: '与承办律师沟通', icon: 'ChatDotRound' },
]

async function load() {
  loading.value = true
  try {
    // 任一接口失败不应阻断整页，各自兜底为空
    const [caseRes, billRes, notifyRes, msgRes] = await Promise.allSettled([
      listMyCases(),
      listMyBills(),
      getNotifyUnread(),
      getMessageUnread(),
    ])
    cases.value = caseRes.status === 'fulfilled' ? caseRes.value || [] : []
    bills.value = billRes.status === 'fulfilled' ? billRes.value || [] : []
    notifyUnread.value = notifyRes.status === 'fulfilled' ? notifyRes.value?.count || 0 : 0
    messageUnread.value = msgRes.status === 'fulfilled' ? msgRes.value?.count || 0 : 0
  } finally {
    loading.value = false
  }
}

function go(path) {
  router.push(path)
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

onMounted(load)
</script>

<style scoped>
.home {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 欢迎条 ---------- */
.hero {
  position: relative;
  overflow: hidden;
  background:
    radial-gradient(ellipse 80% 120% at 88% 10%, rgba(201, 165, 92, 0.22), transparent 60%),
    linear-gradient(135deg, #1a2b4a 0%, var(--brand-navy) 55%, var(--brand-navy-deep) 100%);
  border-radius: 14px;
  padding: 26px 32px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.hero::after {
  content: '';
  position: absolute;
  right: -60px;
  bottom: -90px;
  width: 240px;
  height: 240px;
  border-radius: 50%;
  border: 1px solid rgba(201, 165, 92, 0.3);
  pointer-events: none;
}

.hero-greet {
  font-size: 22px;
  font-weight: 600;
  letter-spacing: 1px;
}

.hero-sub {
  margin: 8px 0 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.6);
  letter-spacing: 0.5px;
}

.hero-badge {
  position: relative;
  z-index: 1;
  padding: 6px 16px;
  border: 1px solid rgba(201, 165, 92, 0.5);
  border-radius: 20px;
  color: var(--brand-gold-light);
  font-size: 12px;
  letter-spacing: 2px;
}

/* ---------- 内容块 ---------- */
.block {
  border-radius: 14px;
}

.block-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.arrow {
  margin-left: 4px;
}

.case-no {
  font-variant-numeric: tabular-nums;
  color: var(--brand-ink);
  font-size: 13px;
}

/* ---------- 快捷入口 ---------- */
.shortcuts {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.sc {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  cursor: pointer;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

.sc:hover {
  transform: translateY(-2px);
  border-color: rgba(201, 165, 92, 0.55);
  box-shadow: 0 6px 18px rgba(20, 30, 55, 0.08);
}

.sc-icon {
  width: 38px;
  height: 38px;
  flex-shrink: 0;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, rgba(201, 165, 92, 0.18), rgba(201, 165, 92, 0.06));
  color: var(--brand-gold-deep);
}

.sc-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.sc-desc {
  margin-top: 3px;
  font-size: 12px;
  color: var(--brand-muted);
}

@media (max-width: 1080px) {
  .shortcuts {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 720px) {
  .hero {
    padding: 20px 22px;
  }
  .shortcuts {
    grid-template-columns: 1fr;
  }
}
</style>
