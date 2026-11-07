<template>
  <div class="doc-editor" v-loading="loading">
    <!-- ============ 页头 ============ -->
    <div class="editor-head">
      <el-button text class="back-btn" @click="goBack">
        <el-icon><ArrowLeft /></el-icon>文书库
      </el-button>

      <div class="head-title">
        <el-input
          v-model="form.title"
          class="title-input"
          placeholder="请输入文书标题"
          maxlength="255"
        />
        <div class="head-meta">
          <span
            class="type-pill"
            :style="{
              background: docTypeMeta(form.doc_type).bg,
              color: docTypeMeta(form.doc_type).color,
            }"
          >
            {{ docTypeMeta(form.doc_type).label }}
          </span>
          <el-tag :type="docStatusMeta(form.status).type" effect="light" size="small">
            {{ docStatusMeta(form.status).label }}
          </el-tag>
          <span v-if="meta.case_title" class="meta-text">
            {{ meta.case_no }} · {{ meta.case_title }}
          </span>
          <span v-if="meta.is_ai_generated" class="ai-badge">AI 生成</span>
          <span v-if="isNew" class="meta-text">新建文书（尚未保存）</span>
        </div>
      </div>

      <div class="head-actions">
        <el-button plain :loading="exporting" @click="exportDoc">
          <el-icon><Download /></el-icon>导出 docx
        </el-button>
        <el-button type="primary" :loading="saving" @click="save">
          <el-icon><Check /></el-icon>保存
        </el-button>
        <el-button v-if="!isNew" link type="danger" class="del-btn" @click="removeDoc">
          <el-icon><Delete /></el-icon>
        </el-button>
      </div>
    </div>

    <!-- ============ 主体：编辑器 + 侧栏 ============ -->
    <div class="editor-main">
      <el-card shadow="never" class="edit-card">
        <div class="meta-bar">
          <div class="field">
            <label>文书类型</label>
            <el-select v-model="form.doc_type" placeholder="选择类型" clearable class="w140">
              <el-option
                v-for="t in docTypeOptions()"
                :key="t.value"
                :label="t.label"
                :value="t.value"
              />
            </el-select>
          </div>

          <div class="field">
            <label>关联案件</label>
            <el-select
              v-model="form.case_id"
              placeholder="不关联案件"
              clearable
              filterable
              class="w260"
            >
              <el-option
                v-for="c in caseOptions"
                :key="c.id"
                :label="`${c.case_no} · ${c.title}`"
                :value="c.id"
              />
            </el-select>
          </div>

          <div class="field status-field">
            <label>状态</label>
            <el-radio-group v-model="form.status" size="small" class="status-group">
              <el-radio-button value="draft">草稿</el-radio-button>
              <el-radio-button value="final">定稿</el-radio-button>
              <el-radio-button value="published">发布给客户</el-radio-button>
            </el-radio-group>
          </div>

          <div class="spacer" />
          <span class="save-hint" :class="{ dirty: isDirty }">
            {{ isDirty ? '有未保存的修改' : '已保存' }}
          </span>
        </div>

        <DocRichEditor v-model="form.content" height="calc(100vh - 322px)" />
      </el-card>

      <!-- 侧栏 -->
      <aside class="side">
        <el-card shadow="never" class="side-card">
          <template #header><span class="side-title">文书信息</span></template>
          <div class="info-row">
            <span class="info-label">创建人</span>
            <span class="info-value">{{ meta.creator_name || '—' }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">创建时间</span>
            <span class="info-value">{{ fmtDateTime(meta.created_at) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">更新时间</span>
            <span class="info-value">{{ fmtDateTime(meta.updated_at) }}</span>
          </div>
          <div class="info-row">
            <span class="info-label">docx</span>
            <span class="info-value">
              <template v-if="meta.has_file">
                <el-button link type="primary" size="small" @click="downloadDoc">
                  下载已导出文件
                </el-button>
              </template>
              <span v-else class="muted">尚未导出</span>
            </span>
          </div>
          <div class="info-row">
            <span class="info-label">案件编号</span>
            <span class="info-value">{{ meta.case_no || '—' }}</span>
          </div>
        </el-card>

        <el-card v-if="missing.length" shadow="never" class="side-card">
          <template #header>
            <span class="side-title">待补全变量</span>
          </template>
          <p class="tip-text">以下占位符没有取到案件数据，请在正文中手工补全：</p>
          <div class="missing-list">
            <el-tag
              v-for="m in missing"
              :key="m"
              type="warning"
              effect="plain"
              size="small"
            >
              {{ '{' + m + '}' }}
            </el-tag>
          </div>
        </el-card>

        <el-card shadow="never" class="side-card">
          <template #header><span class="side-title">写作与发布</span></template>
          <ul class="tips">
            <li>正文按法律文书排版导出：标题居中，正文宋体小四、1.5 倍行距。</li>
            <li>「发布给客户」后，客户可在「我的文书」中在线查看并下载 docx。</li>
            <li>导出会按当前内容生成 docx 并覆盖上一份文件。</li>
            <li>图片以 base64 内嵌，单张不超过 5MB。</li>
          </ul>
        </el-card>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  ArrowLeft,
  Check,
  Delete,
  Download,
} from '@element-plus/icons-vue'
import { listCases } from '@/api/cases'
import {
  createDocument,
  deleteDocument,
  downloadDocument,
  exportDocument,
  generateDocument,
  getDocument,
  updateDocument,
} from '@/api/documents'
import DocRichEditor from '@/components/DocRichEditor.vue'
import {
  docTypeOptions,
  ensureDocDicts,
  canonicalHtml,
  docStatusMeta,
  docTypeMeta,
  fmtDateTime,
  saveBlobResponse,
} from '@/utils/document'

// 文书类型下拉跟管理端字典走，setup 时拉一次
ensureDocDicts()

const route = useRoute()
const router = useRouter()

const loading = ref(false)
const saving = ref(false)
const exporting = ref(false)
const caseOptions = ref([])
const missing = ref([])

const docId = ref(null)
const isNew = computed(() => route.params.id === 'new')
const base = computed(() => (route.path.startsWith('/admin') ? '/admin' : '/lawyer'))

const form = reactive({
  title: '',
  doc_type: '',
  case_id: '',
  content: '',
  status: 'draft',
})

const meta = reactive({
  status: 'draft',
  creator_name: '',
  created_at: '',
  updated_at: '',
  case_no: '',
  case_title: '',
  is_ai_generated: false,
  ai_session_id: null,
  has_file: false,
})

// 保存快照：用于判断是否有未保存修改（正文按归一化 HTML 比较）
const snapshot = ref('')

const isDirty = computed(() => buildSnapshot() !== snapshot.value)

function buildSnapshot() {
  return JSON.stringify({
    title: form.title,
    doc_type: form.doc_type,
    case_id: form.case_id,
    content: canonicalHtml(form.content),
    status: form.status,
  })
}

function applyDoc(doc) {
  docId.value = doc.id
  form.title = doc.title || ''
  form.doc_type = doc.doc_type || ''
  form.case_id = doc.case_id || ''
  form.content = doc.content || ''
  form.status = doc.status || 'draft'

  meta.status = doc.status
  meta.creator_name = doc.creator_name
  meta.created_at = doc.created_at
  meta.updated_at = doc.updated_at
  meta.case_no = doc.case_no
  meta.case_title = doc.case_title
  meta.is_ai_generated = doc.is_ai_generated
  meta.ai_session_id = doc.ai_session_id
  meta.has_file = doc.has_file
  snapshot.value = buildSnapshot()
}

async function loadCases() {
  try {
    const data = await listCases({ page: 1, page_size: 100 })
    caseOptions.value = data.items || []
  } catch {
    caseOptions.value = []
  }
}

async function loadDoc() {
  loading.value = true
  try {
    const doc = await getDocument(route.params.id)
    applyDoc(doc)
  } finally {
    loading.value = false
  }
}

// 从模板进入：/documents/new?template_id=&case_id=&title=
async function generateDraft() {
  const templateId = Number(route.query.template_id)
  if (!templateId) return
  loading.value = true
  try {
    const data = await generateDocument({
      template_id: templateId,
      case_id: route.query.case_id ? Number(route.query.case_id) : null,
      title: route.query.title || null,
    })
    form.title = data.title
    form.doc_type = data.doc_type
    form.case_id = data.case_id || ''
    form.content = data.content
    form.status = 'draft'
    meta.status = 'draft'
    meta.case_no = data.case_no
    const caseItem = caseOptions.value.find((c) => c.id === data.case_id)
    meta.case_title = caseItem ? caseItem.title : ''
    missing.value = data.missing || []
    snapshot.value = '' // 生成的内容尚未保存
    if (data.missing?.length) {
      ElMessage.warning(`有 ${data.missing.length} 个变量未取到值，请手工补全`)
    } else {
      ElMessage.success('已按模板填充，请确认内容后保存')
    }
  } finally {
    loading.value = false
  }
}

function payload() {
  return {
    title: form.title.trim(),
    doc_type: form.doc_type || null,
    case_id: form.case_id || null,
    content: form.content || '',
    status: form.status,
    is_ai_generated: meta.is_ai_generated,
    ai_session_id: meta.ai_session_id,
  }
}

async function save() {
  if (!form.title.trim()) {
    ElMessage.warning('请先填写文书标题')
    return false
  }
  saving.value = true
  try {
    const data = payload()
    let doc
    if (isNew.value) {
      doc = await createDocument(data)
      ElMessage.success('文书已创建')
    } else {
      doc = await updateDocument(docId.value, data)
      ElMessage.success('已保存')
    }
    applyDoc(doc)
    if (isNew.value) {
      // 用 replace 让刷新/分享后仍停留在同一份文书
      router.replace(`${base.value}/documents/${doc.id}`)
    }
    return true
  } catch {
    return false
  } finally {
    saving.value = false
  }
}

async function ensureSaved() {
  if (!isNew.value && !isDirty.value) return true
  return await save()
}

async function exportDoc() {
  if (!(await ensureSaved())) return
  exporting.value = true
  try {
    const result = await exportDocument(docId.value)
    const response = await downloadDocument(docId.value)
    const name = saveBlobResponse(response, result.file_name)
    meta.has_file = true
    ElMessage.success(`已导出 ${name}`)
  } finally {
    exporting.value = false
  }
}

async function downloadDoc() {
  const response = await downloadDocument(docId.value)
  saveBlobResponse(response, `${form.title || '文书'}.docx`)
}

async function removeDoc() {
  try {
    await ElMessageBox.confirm(
      `删除后文书及其导出的 docx 文件都会移除，确定删除「${form.title}」吗？`,
      '删除文书',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteDocument(docId.value)
  ElMessage.success('文书已删除')
  snapshot.value = buildSnapshot()
  router.replace(`${base.value}/documents`)
}

function goBack() {
  router.push(`${base.value}/documents`)
}

onBeforeRouteLeave(async () => {
  if (!isDirty.value) return true
  try {
    await ElMessageBox.confirm('当前修改尚未保存，确定离开吗？', '未保存的修改', {
      type: 'warning',
      confirmButtonText: '离开',
      cancelButtonText: '继续编辑',
    })
    return true
  } catch {
    return false
  }
})

onMounted(async () => {
  await loadCases()
  if (isNew.value) {
    await generateDraft()
    if (!form.title && !route.query.template_id) snapshot.value = buildSnapshot()
  } else {
    await loadDoc()
  }
})
</script>

<style scoped>
.doc-editor {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

/* ---------- 页头 ---------- */
.editor-head {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 14px 18px;
  display: flex;
  align-items: center;
  gap: 16px;
}

.back-btn {
  color: var(--brand-muted);
  padding: 0;
}

.back-btn:hover {
  color: var(--brand-gold-deep);
}

.head-title {
  flex: 1;
  min-width: 0;
}

.title-input :deep(.el-input__wrapper) {
  box-shadow: none;
  padding: 0;
  background: transparent;
}

.title-input :deep(.el-input__inner) {
  font-size: 19px;
  font-weight: 600;
  color: var(--brand-ink);
  letter-spacing: 0.5px;
  height: 30px;
}

.title-input :deep(.el-input__inner::placeholder) {
  font-weight: 500;
  color: #b7bdc9;
}

.head-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 4px;
  flex-wrap: wrap;
}

.type-pill {
  display: inline-block;
  padding: 0 8px;
  border-radius: 10px;
  font-size: 11px;
  line-height: 19px;
}

.meta-text {
  font-size: 12px;
  color: var(--brand-muted);
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

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.del-btn {
  margin-left: 0;
}

/* ---------- 主体 ---------- */
.editor-main {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 16px;
  align-items: start;
}

.edit-card {
  border-radius: 12px;
  border: 1px solid var(--brand-line);
}

.edit-card :deep(.el-card__body) {
  padding: 14px 16px 16px;
}

.meta-bar {
  display: flex;
  align-items: center;
  gap: 18px;
  flex-wrap: wrap;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px dashed var(--brand-line);
}

.field {
  display: flex;
  align-items: center;
  gap: 8px;
}

/* 只作用于字段自身的说明文字：el-radio-button 也是 <label>，不能误伤 */
.field > label {
  font-size: 12px;
  color: var(--brand-muted);
  white-space: nowrap;
}

.w140 {
  width: 140px;
}

.w260 {
  width: 260px;
}

/* ---------- 状态选择：金色高亮胶囊，方便一眼定位 ---------- */
.status-field {
  gap: 10px;
  padding: 3px 10px 3px 12px;
  border-radius: 999px;
  background: linear-gradient(135deg, #fdf8ec 0%, #faf1dd 100%);
  border: 1px solid #e6d4ac;
  box-shadow: 0 1px 4px rgba(165, 129, 61, 0.14);
}

.field.status-field > label {
  position: relative;
  padding-left: 9px;
  color: var(--brand-gold-deep);
  font-weight: 600;
  letter-spacing: 0.6px;
}

.field.status-field > label::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 12px;
  border-radius: 2px;
  background: var(--brand-gold);
}

/* 分段控件：去掉 Element 默认的分段描边，避免与金色外框叠出重影 */
.status-group {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  background: #fffdf8;
  border: 1px solid #ecdfbf;
  border-radius: 999px;
}

.status-group :deep(.el-radio-button) {
  margin: 0;
}

.status-group :deep(.el-radio-button__inner) {
  display: inline-flex;
  align-items: center;
  height: 24px;
  padding: 0 12px;
  font-size: 12px;
  color: #8a7a58;
  background: transparent;
  border: none;
  border-radius: 999px;
  box-shadow: none;
  transition: background-color 0.18s ease, color 0.18s ease;
}

.status-group :deep(.el-radio-button__inner:hover) {
  color: var(--brand-gold-deep);
  background: #fbf0d9;
}

.status-group :deep(.el-radio-button.is-active .el-radio-button__inner) {
  font-weight: 600;
  color: #fff;
  background: var(--brand-navy-soft);
  border: none;
  border-radius: 999px;
  box-shadow: 0 1px 3px rgba(29, 43, 71, 0.22);
}

.spacer {
  flex: 1;
}

.save-hint {
  font-size: 12px;
  color: var(--brand-muted);
}

.save-hint.dirty {
  color: var(--brand-gold-deep);
  font-weight: 500;
}

/* ---------- 侧栏 ---------- */
.side {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.side-card {
  border-radius: 12px;
  border: 1px solid var(--brand-line);
}

.side-card :deep(.el-card__header) {
  padding: 12px 16px;
}

.side-card :deep(.el-card__body) {
  padding: 12px 16px 14px;
}

.side-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
}

.info-row {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 5px 0;
  font-size: 12px;
}

.info-label {
  width: 62px;
  flex-shrink: 0;
  color: var(--brand-muted);
}

.info-value {
  flex: 1;
  color: var(--brand-text);
  word-break: break-all;
}

.muted {
  color: var(--brand-muted);
}

.tip-text {
  margin: 0 0 8px;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.7;
}

.missing-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.tips {
  margin: 0;
  padding-left: 16px;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.9;
}

@media (max-width: 1280px) {
  .editor-main {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
