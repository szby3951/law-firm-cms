<template>
  <div class="my-docs">
    <!-- ============ 概览 ============ -->
    <div class="summary">
      <div class="summary-left">
        <div class="summary-icon">
          <el-icon :size="22"><Document /></el-icon>
        </div>
        <div>
          <div class="summary-title">我的文书</div>
          <div class="summary-sub">
            共 {{ rows.length }} 份 · 律师发布后可在线查看并下载 docx<span v-if="latestText">，最近更新 {{ latestText }}</span>
          </div>
        </div>
      </div>
      <el-button plain class="refresh-btn" @click="load">
        <el-icon><Refresh /></el-icon>刷新
      </el-button>
    </div>

    <!-- ============ 筛选 ============ -->
    <div class="filter-bar">
      <el-radio-group v-model="typeFilter" size="default">
        <el-radio-button value="all">全部</el-radio-button>
        <el-radio-button v-for="t in usedTypes" :key="t.value" :value="t.value">
          {{ t.label }}<span class="tab-count">{{ t.count }}</span>
        </el-radio-button>
      </el-radio-group>

      <el-input
        v-model="keyword"
        placeholder="搜索文书标题"
        clearable
        class="kw"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <!-- ============ 文书卡片 ============ -->
    <div v-loading="loading" class="doc-grid">
      <el-empty
        v-if="!loading && !filtered.length"
        :description="rows.length ? '没有匹配的文书' : '律师尚未向您发布文书'"
        :image-size="110"
      />

      <div
        v-for="doc in filtered"
        :key="doc.id"
        class="doc-card"
        @click="openDetail(doc)"
      >
        <div class="card-top">
          <div
            class="doc-icon"
            :style="{
              background: docTypeMeta(doc.doc_type).bg,
              color: docTypeMeta(doc.doc_type).color,
            }"
          >
            <el-icon :size="20"><component :is="docTypeMeta(doc.doc_type).icon" /></el-icon>
          </div>
          <div class="card-head">
            <div class="doc-title">{{ doc.title }}</div>
            <div class="doc-tags">
              <span
                class="type-pill"
                :style="{
                  background: docTypeMeta(doc.doc_type).bg,
                  color: docTypeMeta(doc.doc_type).color,
                }"
              >
                {{ doc.doc_type_label }}
              </span>
              <span class="case-text">{{ doc.case_no || '未关联案件' }}</span>
            </div>
          </div>
        </div>

        <div class="doc-excerpt">{{ doc.excerpt || '正文暂无摘要' }}</div>

        <div class="card-foot">
          <span class="time">{{ fmtDateTime(doc.updated_at) }}</span>
          <div class="grow" />
          <el-button link type="primary" size="small" @click.stop="openDetail(doc)">
            查看
          </el-button>
          <el-button link type="primary" size="small" @click.stop="download(doc)">
            下载 docx
          </el-button>
        </div>
      </div>
    </div>

    <!-- ============ 在线预览 ============ -->
    <el-dialog
      v-model="detailVisible"
      :title="detail?.title || '文书详情'"
      width="820px"
      top="5vh"
    >
      <div v-if="detail" class="detail-meta">
        <span
          class="type-pill"
          :style="{
            background: docTypeMeta(detail.doc_type).bg,
            color: docTypeMeta(detail.doc_type).color,
          }"
        >
          {{ detail.doc_type_label }}
        </span>
        <span class="meta-text">{{ detail.case_no }} · {{ detail.case_title }}</span>
        <span class="meta-text">更新于 {{ fmtDateTime(detail.updated_at) }}</span>
      </div>

      <div class="detail-body" v-loading="detailLoading">
        <div class="detail-doc" v-html="detail?.content || '<p>正文暂无内容</p>'" />
      </div>

      <template #footer>
        <span class="detail-tip">如需纸质版，可下载 docx 后打印</span>
        <el-button @click="detailVisible = false">关闭</el-button>
        <el-button type="primary" @click="download(detail)">
          <el-icon><Download /></el-icon>下载 docx
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Document, Download, Refresh, Search } from '@element-plus/icons-vue'
import {
  downloadMyDocument,
  getMyDocument,
  listMyDocuments,
} from '@/api/documents'
import {
  DOC_TYPE_META,
  docTypeMeta,
  fmtDateTime,
  saveBlobResponse,
} from '@/utils/document'

const loading = ref(false)
const rows = ref([])
const typeFilter = ref('all')
const keyword = ref('')

const detailVisible = ref(false)
const detailLoading = ref(false)
const detail = ref(null)

const usedTypes = computed(() => {
  const counter = {}
  rows.value.forEach((d) => {
    if (d.doc_type) counter[d.doc_type] = (counter[d.doc_type] || 0) + 1
  })
  return Object.entries(counter).map(([value, count]) => ({
    value,
    count,
    label: DOC_TYPE_META[value]?.label || value,
  }))
})

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return rows.value.filter((d) => {
    if (typeFilter.value !== 'all' && d.doc_type !== typeFilter.value) return false
    if (kw && !d.title.toLowerCase().includes(kw)) return false
    return true
  })
})

const latestText = computed(() => {
  if (!rows.value.length) return ''
  const latest = rows.value
    .map((d) => d.updated_at)
    .filter(Boolean)
    .sort()
    .pop()
  return latest ? fmtDateTime(latest) : ''
})

async function load() {
  loading.value = true
  try {
    rows.value = await listMyDocuments()
  } finally {
    loading.value = false
  }
}

async function openDetail(doc) {
  detail.value = doc
  detailVisible.value = true
  detailLoading.value = true
  try {
    detail.value = await getMyDocument(doc.id)
  } finally {
    detailLoading.value = false
  }
}

async function download(doc) {
  if (!doc?.id) return
  const response = await downloadMyDocument(doc.id)
  const name = saveBlobResponse(response, `${doc.title}.docx`)
  ElMessage.success(`已下载 ${name}`)
}

onMounted(load)
</script>

<style scoped>
.my-docs {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 概览 ---------- */
.summary {
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 60%, var(--brand-navy-deep) 100%);
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
  color: rgba(255, 255, 255, 0.6);
}

.refresh-btn {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.24);
  color: #fff;
}

.refresh-btn:hover {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.36);
  color: #fff;
}

/* ---------- 筛选 ---------- */
.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.tab-count {
  margin-left: 4px;
  font-size: 11px;
  opacity: 0.7;
}

.kw {
  width: 220px;
  margin-left: auto;
}

/* ---------- 卡片 ---------- */
.doc-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  min-height: 160px;
}

.doc-grid :deep(.el-empty) {
  grid-column: 1 / -1;
}

.doc-card {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 16px 18px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  cursor: pointer;
  transition: all 0.18s;
}

.doc-card:hover {
  border-color: var(--brand-gold-light);
  box-shadow: 0 6px 18px rgba(20, 33, 61, 0.08);
  transform: translateY(-1px);
}

.card-top {
  display: flex;
  gap: 12px;
}

.doc-icon {
  width: 42px;
  height: 42px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.card-head {
  min-width: 0;
  flex: 1;
}

.doc-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-tags {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
}

.type-pill {
  display: inline-block;
  padding: 0 7px;
  border-radius: 9px;
  font-size: 11px;
  line-height: 18px;
  flex-shrink: 0;
}

.case-text {
  font-size: 11px;
  color: var(--brand-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.doc-excerpt {
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.7;
  height: 38px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.card-foot {
  display: flex;
  align-items: center;
  gap: 4px;
  border-top: 1px dashed var(--brand-line);
  padding-top: 8px;
}

.time {
  font-size: 11px;
  color: var(--brand-muted);
}

.grow {
  flex: 1;
}

/* ---------- 详情 ---------- */
.detail-meta {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--brand-line);
  margin-bottom: 14px;
}

.meta-text {
  font-size: 12px;
  color: var(--brand-muted);
}

.detail-body {
  max-height: 58vh;
  overflow-y: auto;
  background: #fbfbfd;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 20px 26px;
}

.detail-doc {
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
  font-size: 14px;
  line-height: 2;
  color: var(--brand-text);
}

.detail-doc :deep(p) {
  margin: 0 0 6px;
}

.detail-doc :deep(h1),
.detail-doc :deep(h2),
.detail-doc :deep(h3) {
  font-size: 16px;
  margin: 12px 0 6px;
  color: var(--brand-ink);
}

.detail-doc :deep(table) {
  border-collapse: collapse;
  width: 100%;
  margin: 8px 0;
}

.detail-doc :deep(td),
.detail-doc :deep(th) {
  border: 1px solid var(--brand-line);
  padding: 6px 8px;
  font-size: 13px;
}

.detail-tip {
  float: left;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 32px;
}

@media (max-width: 1100px) {
  .doc-grid {
    grid-template-columns: 1fr;
  }
}
</style>
