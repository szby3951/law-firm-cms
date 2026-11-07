<template>
  <div class="client-list">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-input
        v-model="query.keyword"
        placeholder="搜索姓名 / 电话 / 证件号"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="query.status" placeholder="漏斗状态" clearable class="sel" @change="search">
        <el-option label="潜在" value="potential" />
        <el-option label="成交" value="deal" />
        <el-option label="流失" value="lost" />
      </el-select>

      <el-select v-model="query.level" placeholder="客户分级" clearable class="sel" @change="search">
        <el-option label="VIP" value="vip" />
        <el-option label="普通" value="normal" />
      </el-select>

      <el-select v-model="query.source" placeholder="来源渠道" clearable class="sel" @change="search">
        <el-option label="转介绍" value="转介绍" />
        <el-option label="网络" value="网络" />
        <el-option label="门店" value="门店" />
      </el-select>

      <div class="spacer" />

      <el-button @click="handleExport" :loading="exporting">
        <el-icon><Download /></el-icon>导出
      </el-button>
      <el-button type="primary" @click="openForm()">
        <el-icon><Plus /></el-icon>新增客户
      </el-button>
    </div>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column prop="name" label="姓名" min-width="120">
          <template #default="{ row }">
            <div class="name-cell">
              <span class="name">{{ row.name }}</span>
              <el-tag v-if="row.client_type === 'company'" size="small" effect="plain">机构</el-tag>
            </div>
          </template>
        </el-table-column>

        <el-table-column prop="phone" label="电话" min-width="130" />
        <el-table-column prop="id_no" label="证件号" min-width="150" />
        <el-table-column prop="source_channel" label="来源" min-width="90">
          <template #default="{ row }">{{ row.source_channel || '—' }}</template>
        </el-table-column>

        <el-table-column label="分级" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="row.level === 'vip' ? 'warning' : 'info'" effect="light" size="small">
              {{ row.level === 'vip' ? 'VIP' : '普通' }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag :type="statusMeta[row.status]?.type" effect="light" size="small">
              {{ statusMeta[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column prop="created_at" label="创建时间" min-width="150">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>

        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goDetail(row.id)">详情</el-button>
            <el-button link type="primary" @click="openForm(row)">编辑</el-button>
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

    <!-- 新增/编辑表单 -->
    <ClientForm v-model="formVisible" :client="editing" @saved="onSaved" />
  </div>
</template>

<script setup>
import { reactive, ref, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Search, Plus, Download } from '@element-plus/icons-vue'
import { listClients, deleteClient, exportClients } from '@/api/clients'
import { useUserStore } from '@/stores/user'
import ClientForm from './ClientForm.vue'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const isAdmin = computed(() => userStore.role === 'admin')

const loading = ref(false)
const exporting = ref(false)
const rows = ref([])
const total = ref(0)

const query = reactive({
  keyword: '',
  status: '',
  level: '',
  source: '',
  page: 1,
  page_size: 20,
})

const formVisible = ref(false)
const editing = ref(null)

const statusMeta = {
  potential: { label: '潜在', type: 'primary' },
  deal: { label: '成交', type: 'success' },
  lost: { label: '流失', type: 'info' },
}

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.keyword) delete params.keyword
    if (!params.status) delete params.status
    if (!params.level) delete params.level
    if (!params.source) delete params.source
    const data = await listClients(params)
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

function openForm(client = null) {
  editing.value = client
  formVisible.value = true
}

function onSaved() {
  formVisible.value = false
  load()
}

function goDetail(id) {
  // 管理员端复用本组件，详情路径需跟随当前布局前缀（/admin 或 /lawyer）
  const base = route.path.startsWith('/admin') ? '/admin' : '/lawyer'
  router.push(`${base}/clients/${id}`)
}

async function handleDelete(row) {
  try {
    await ElMessageBox.confirm(`确定删除客户「${row.name}」吗？删除后不可恢复。`, '删除确认', {
      confirmButtonText: '删除',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  await deleteClient(row.id)
  ElMessage.success('已删除')
  load()
}

async function handleExport() {
  exporting.value = true
  try {
    const params = { ...query }
    if (!params.keyword) delete params.keyword
    if (!params.status) delete params.status
    if (!params.level) delete params.level
    if (!params.source) delete params.source
    delete params.page
    delete params.page_size

    const res = await exportClients(params)
    // 从响应头解析文件名，失败则用默认名
    const disposition = res.headers?.['content-disposition'] || ''
    const m = disposition.match(/filename="?([^";]+)"?/)
    const filename = m ? decodeURIComponent(m[1]) : 'clients.xlsx'

    const url = window.URL.createObjectURL(new Blob([res.data]))
    const a = document.createElement('a')
    a.href = url
    a.download = filename
    a.click()
    window.URL.revokeObjectURL(url)
    ElMessage.success('导出成功')
  } finally {
    exporting.value = false
  }
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}

load()
</script>

<style scoped>
.client-list {
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
  width: 260px;
}

.filter-bar .sel {
  width: 140px;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.name-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.name-cell .name {
  font-weight: 500;
  color: var(--brand-ink);
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
