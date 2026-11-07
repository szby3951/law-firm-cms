<template>
  <div class="case-list">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.status" placeholder="案件状态" clearable class="sel" @change="search">
        <el-option v-for="(m, k) in statusMeta" :key="k" :label="m.label" :value="k" />
      </el-select>

      <el-input
        v-model="query.cause"
        placeholder="案由 / 关键词"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="query.case_type" placeholder="案件类型" clearable class="sel" @change="search">
        <el-option label="诉讼" value="litigation" />
        <el-option label="非诉" value="non_litigation" />
      </el-select>

      <el-select
        v-if="isAdmin"
        v-model="query.lawyer_id"
        placeholder="承办律师"
        clearable
        filterable
        class="sel"
        @change="search"
      >
        <el-option v-for="l in lawyers" :key="l.lawyer_id" :label="l.lawyer_name" :value="l.lawyer_id" />
      </el-select>

      <el-tag
        v-if="query.client_id"
        closable
        type="info"
        effect="plain"
        class="client-filter"
        @close="clearClientFilter"
      >
        委托客户：{{ clientFilterName }}
      </el-tag>

      <div class="spacer" />

      <el-button type="primary" @click="openForm()">
        <el-icon><Plus /></el-icon>立案
      </el-button>
    </div>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="case_no" label="案号" width="150">
          <template #default="{ row }">
            <span class="case-no">{{ row.case_no }}</span>
          </template>
        </el-table-column>

        <el-table-column prop="title" label="案件标题" min-width="200" show-overflow-tooltip />

        <el-table-column prop="case_cause" label="案由" min-width="110">
          <template #default="{ row }">{{ row.case_cause || '—' }}</template>
        </el-table-column>

        <el-table-column v-if="isAdmin" label="承办律师" width="100">
          <template #default="{ row }">{{ row.lead_lawyer_name || '未分案' }}</template>
        </el-table-column>

        <el-table-column label="类型" width="80" align="center">
          <template #default="{ row }">
            <el-tag :type="row.case_type === 'litigation' ? 'primary' : 'info'" effect="plain" size="small">
              {{ row.case_type === 'litigation' ? '诉讼' : '非诉' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="标的额" width="130" align="right">
          <template #default="{ row }">
            <span class="amount">¥{{ formatAmount(row.amount) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type" effect="light" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="立案时间" min-width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">详情</el-button>
            <el-button v-if="isAdmin" link type="primary" @click="openAssign(row)">分案</el-button>
            <el-button v-if="isAdmin" link type="danger" @click="handleDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next, jumper"
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>

    <!-- 立案表单 -->
    <CaseForm v-model="formVisible" @saved="onSaved" />

    <!-- 分案弹窗（仅管理员） -->
    <AssignDialog v-model="assignVisible" :case-id="assigning?.id" :case-title="assigning?.title" @saved="load" />
  </div>
</template>

<script setup>
import { reactive, ref, computed, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus } from '@element-plus/icons-vue'
import { listCases, listLawyers, deleteCase } from '@/api/cases'
import { useUserStore } from '@/stores/user'
import CaseForm from './CaseForm.vue'
import AssignDialog from './AssignDialog.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.role === 'admin')

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const lawyers = ref([])

const query = reactive({
  status: '',
  cause: '',
  case_type: '',
  lawyer_id: '',
  client_id: '',
  page: 1,
  page_size: 20,
})

// 从客户详情跳转过来时，按该客户筛选（?client_id=&client_name=）
if (route.query.client_id) query.client_id = Number(route.query.client_id)

const clientFilterName = computed(() => route.query.client_name || `客户 #${query.client_id}`)

const formVisible = ref(false)
const assignVisible = ref(false)
const assigning = ref(null)

const statusMeta = {
  consulting: { label: '咨询中', type: 'primary' },
  filed: { label: '已立案', type: 'warning' },
  handling: { label: '办理中', type: 'success' },
  pending_close: { label: '待结案', type: 'info' },
  closed: { label: '已结案', type: 'success' },
  withdrawn: { label: '已退案', type: 'danger' },
}

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.status) delete params.status
    if (!params.cause) delete params.cause
    if (!params.case_type) delete params.case_type
    if (!params.lawyer_id) delete params.lawyer_id
    if (!params.client_id) delete params.client_id
    const data = await listCases(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

// 客户详情跳过来时带 ?client_id=，路由变化需同步筛选（同组件复用不重新挂载）
watch(
  () => route.query.client_id,
  (v) => {
    query.client_id = v ? Number(v) : ''
    query.page = 1
    load()
  },
)

function clearClientFilter() {
  router.replace({ path: route.path, query: {} })
}

function openForm() {
  formVisible.value = true
}

function onSaved() {
  formVisible.value = false
  load()
}

function openAssign(row) {
  assigning.value = row
  assignVisible.value = true
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(
      `确定删除案件「${row.title}」（${row.case_no}）吗？删除后不可恢复。`,
      '删除确认',
      {
        confirmButtonText: '删除',
        cancelButtonText: '取消',
        type: 'warning',
      },
    )
  } catch {
    return
  }
  await deleteCase(row.id)
  ElMessage.success('已删除')
  load()
}

function goDetail(id) {
  // 管理员端复用本组件，详情路径跟随当前布局前缀（/admin 或 /lawyer）
  const base = route.path.startsWith('/admin') ? '/admin' : '/lawyer'
  router.push(`${base}/cases/${id}`)
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

function formatAmount(v) {
  if (v === null || v === undefined) return '0'
  const n = Number(v)
  return n.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
}

// 管理员加载律师列表供筛选与分案
if (isAdmin.value) {
  listLawyers().then((list) => (lawyers.value = list))
}

load()
</script>

<style scoped>
.case-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar .kw {
  width: 220px;
}

.filter-bar .sel {
  width: 150px;
}

.client-filter {
  max-width: 220px;
  overflow: hidden;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.case-no {
  font-weight: 500;
  color: var(--brand-navy-soft);
  font-family: 'SFMono-Regular', Consolas, monospace;
}

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

/* ---------- 手机端：筛选栏竖排占满整行，避免输入框被压成一条 ---------- */
@media (max-width: 768px) {
  .filter-bar {
    gap: 8px;
  }

  .filter-bar .kw,
  .filter-bar .sel,
  .filter-bar .el-select,
  .filter-bar .el-date-editor,
  .filter-bar .client-filter {
    width: 100% !important;
    max-width: none;
  }

  .spacer {
    display: none;
  }
}
</style>
