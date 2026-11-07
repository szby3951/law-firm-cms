<template>
  <div class="doc-list">
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

    <!-- ============ 筛选 ============ -->
    <div class="filter-bar">
      <el-select v-model="query.doc_type" placeholder="文书类型" clearable class="sel" @change="search">
        <el-option v-for="t in docTypeOptions()" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>

      <el-select v-model="query.status" placeholder="文书状态" clearable class="sel" @change="search">
        <el-option v-for="s in DOC_STATUS_OPTIONS" :key="s.value" :label="s.label" :value="s.value" />
      </el-select>

      <el-select
        v-model="query.case_id"
        placeholder="关联案件"
        clearable
        filterable
        class="case-sel"
        @change="search"
      >
        <el-option
          v-for="c in caseOptions"
          :key="c.id"
          :label="`${c.case_no} · ${c.title}`"
          :value="c.id"
        />
      </el-select>

      <el-input
        v-model="query.keyword"
        placeholder="文书标题关键词"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-button text class="reset-btn" @click="resetQuery">重置</el-button>
    </div>

    <!-- ============ 文书列表 ============ -->
    <el-card shadow="never" class="table-card">
      <template #header>
        <div class="card-head">
          <div class="head-left">
            <span>文书库</span>
            <span class="sub">共 {{ total }} 份 · 按案件归档，律师仅见本人及本人承办案件的文书</span>
          </div>
          <div class="head-actions">
            <el-button plain @click="goTemplates">
              <el-icon><Collection /></el-icon>模板库
            </el-button>
            <el-button plain type="warning" @click="genVisible = true">
              <el-icon><MagicStick /></el-icon>从模板生成
            </el-button>
            <el-button type="primary" @click="goEditor()">
              <el-icon><Plus /></el-icon>新建文书
            </el-button>
          </div>
        </div>
      </template>

      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="文书标题" min-width="260">
          <template #default="{ row }">
            <div class="title-cell">
              <div class="title-line">
                <el-link type="primary" :underline="false" @click="goEditor(row.id)">
                  {{ row.title }}
                </el-link>
                <span v-if="row.is_ai_generated" class="ai-badge">AI 生成</span>
              </div>
              <div class="excerpt">{{ row.excerpt || '正文尚未填写' }}</div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="类型" width="110" align="center">
          <template #default="{ row }">
            <span
              class="type-pill"
              :style="{ background: docTypeMeta(row.doc_type).bg, color: docTypeMeta(row.doc_type).color }"
            >
              {{ row.doc_type_label }}
            </span>
          </template>
        </el-table-column>

        <el-table-column label="关联案件" min-width="180">
          <template #default="{ row }">
            <div v-if="row.case_id" class="case-cell">
              <span class="case-title">{{ row.case_title }}</span>
              <span class="case-no">{{ row.case_no }}</span>
            </div>
            <span v-else class="muted">未关联案件</span>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="96" align="center">
          <template #default="{ row }">
            <el-tag :type="docStatusMeta(row.status).type" effect="light" size="small">
              {{ row.status_label }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="创建人" width="100">
          <template #default="{ row }">{{ row.creator_name || '—' }}</template>
        </el-table-column>

        <el-table-column label="更新时间" width="140">
          <template #default="{ row }">
            <span class="muted">{{ fmtDateTime(row.updated_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="docx" width="88" align="center">
          <template #default="{ row }">
            <el-tooltip
              v-if="row.has_file"
              content="已导出，可下载"
              placement="top"
            >
              <el-icon class="has-file"><DocumentChecked /></el-icon>
            </el-tooltip>
            <span v-else class="muted small">未导出</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="170" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="goEditor(row.id)">编辑</el-button>
            <el-button link type="primary" :loading="exportingId === row.id" @click="exportRow(row)">
              导出
            </el-button>
            <el-button link type="danger" @click="removeRow(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-if="!loading && !rows.length" description="暂无文书，试试从模板生成一份" :image-size="100" />

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

    <!-- 从模板生成 -->
    <GenerateDocDialog v-model="genVisible" :case-options="caseOptions" @open="openGenerated" />
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Collection,
  DocumentChecked,
  MagicStick,
  Plus,
  Search,
} from '@element-plus/icons-vue'
import { listCases } from '@/api/cases'
import {
  deleteDocument,
  downloadDocument,
  exportDocument,
  listDocuments,
} from '@/api/documents'
import {
  DOC_STATUS_OPTIONS,
  docTypeOptions,
  ensureDocDicts,
  docStatusMeta,
  docTypeMeta,
  fmtDateTime,
  saveBlobResponse,
} from '@/utils/document'
import GenerateDocDialog from './GenerateDocDialog.vue'

// 文书类型下拉跟管理端字典走，setup 时拉一次
ensureDocDicts()

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const exportingId = ref(null)
const genVisible = ref(false)
const caseOptions = ref([])
const stats = reactive({ all: 0, draft: 0, final: 0, published: 0 })

const query = reactive({
  doc_type: '',
  status: '',
  case_id: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

const base = computed(() => (route.path.startsWith('/admin') ? '/admin' : '/lawyer'))

const statCards = computed(() => [
  {
    label: '全部文书',
    value: stats.all,
    icon: 'Document',
    bg: '#eef1f7',
    color: 'var(--brand-navy)',
  },
  {
    label: '草稿',
    value: stats.draft,
    icon: 'EditPen',
    bg: '#eef0f4',
    color: '#5b6478',
  },
  {
    label: '定稿',
    value: stats.final,
    icon: 'CircleCheck',
    bg: '#f9f2e2',
    color: '#a5813d',
  },
  {
    label: '已发布给客户',
    value: stats.published,
    icon: 'Promotion',
    bg: '#e8f4ef',
    color: '#1f5f4a',
  },
])

async function load() {
  loading.value = true
  try {
    const params = { page: query.page, page_size: query.page_size }
    if (query.doc_type) params.doc_type = query.doc_type
    if (query.status) params.status = query.status
    if (query.case_id) params.case_id = query.case_id
    if (query.keyword) params.keyword = query.keyword
    const data = await listDocuments(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

async function loadStats() {
  const count = async (status) => {
    try {
      const params = { page: 1, page_size: 1 }
      if (status) params.status = status
      const data = await listDocuments(params)
      return data.total
    } catch {
      return 0
    }
  }
  const [all, draft, final, published] = await Promise.all([
    count(''),
    count('draft'),
    count('final'),
    count('published'),
  ])
  stats.all = all
  stats.draft = draft
  stats.final = final
  stats.published = published
}

async function loadCases() {
  try {
    const data = await listCases({ page: 1, page_size: 100 })
    caseOptions.value = data.items || []
  } catch {
    caseOptions.value = []
  }
}

function search() {
  query.page = 1
  load()
}

function resetQuery() {
  query.doc_type = ''
  query.status = ''
  query.case_id = ''
  query.keyword = ''
  search()
}

function goEditor(id) {
  router.push(id ? `${base.value}/documents/${id}` : `${base.value}/documents/new`)
}

function goTemplates() {
  router.push(`${base.value}/doc-templates`)
}

function openGenerated(payload) {
  genVisible.value = false
  router.push({
    path: `${base.value}/documents/new`,
    query: {
      template_id: payload.template_id,
      case_id: payload.case_id || undefined,
      title: payload.title || undefined,
    },
  })
}

async function exportRow(row) {
  exportingId.value = row.id
  try {
    await exportDocument(row.id)
    const response = await downloadDocument(row.id)
    const name = saveBlobResponse(response, `${row.title}.docx`)
    ElMessage.success(`已导出 ${name}`)
    load()
    loadStats()
  } finally {
    exportingId.value = null
  }
}

async function removeRow(row) {
  try {
    await ElMessageBox.confirm(
      `删除后文书及其导出的 docx 文件都会移除，确定删除「${row.title}」吗？`,
      '删除文书',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteDocument(row.id)
  ElMessage.success('文书已删除')
  if (rows.value.length === 1 && query.page > 1) query.page -= 1
  load()
  loadStats()
}

onMounted(() => {
  load()
  loadStats()
  loadCases()
})
</script>

<style scoped>
.doc-list {
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
  padding: 18px 20px;
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-icon {
  width: 44px;
  height: 44px;
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

/* ---------- 筛选 ---------- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar .sel {
  width: 140px;
}

.filter-bar .case-sel {
  width: 240px;
}

.filter-bar .kw {
  width: 210px;
}

.reset-btn {
  color: var(--brand-muted);
}

.spacer {
  flex: 1;
}

/* ---------- 列表 ---------- */
.table-card {
  border-radius: 12px;
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
}

.head-left .sub {
  font-size: 12px;
  color: var(--brand-muted);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.title-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.title-line {
  display: flex;
  align-items: center;
  gap: 6px;
}

.ai-badge {
  font-size: 10px;
  line-height: 16px;
  padding: 0 5px;
  border-radius: 3px;
  color: #4b3f72;
  background: #eeecf6;
  border: 1px solid #ddd8ef;
}

.excerpt {
  font-size: 12px;
  color: var(--brand-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 420px;
}

.type-pill {
  display: inline-block;
  padding: 1px 8px;
  border-radius: 10px;
  font-size: 12px;
  line-height: 20px;
}

.case-cell {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.case-title {
  font-size: 13px;
  color: var(--brand-text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.case-no {
  font-size: 11px;
  color: var(--brand-muted);
  letter-spacing: 0.3px;
}

.muted {
  color: var(--brand-muted);
  font-size: 12px;
}

.muted.small {
  font-size: 11px;
}

.has-file {
  color: var(--brand-gold-deep);
  font-size: 16px;
}

.pager {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

@media (max-width: 1200px) {
  .stat-row {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
