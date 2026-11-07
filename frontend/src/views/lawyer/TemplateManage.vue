<template>
  <div class="tpl-manage">
    <!-- ============ 左：模板列表 ============ -->
    <div class="tpl-side">
      <div class="side-head">
        <span class="side-title">文书模板库</span>
        <el-button size="small" type="primary" plain @click="startCreate">
          <el-icon><Plus /></el-icon>新建
        </el-button>
      </div>

      <el-input
        v-model="keyword"
        placeholder="搜索模板名称"
        clearable
        size="default"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <el-select v-model="typeFilter" placeholder="全部类型" clearable size="default">
        <el-option v-for="t in docTypeOptions()" :key="t.value" :label="t.label" :value="t.value" />
      </el-select>

      <el-scrollbar v-loading="loading" class="tpl-scroll">
        <div
          v-for="tpl in filtered"
          :key="tpl.id"
          class="tpl-row"
          :class="{ active: form.id === tpl.id }"
          @click="selectTemplate(tpl)"
        >
          <div class="row-head">
            <span class="row-name">{{ tpl.name }}</span>
            <span
              class="row-type"
              :style="{
                background: docTypeMeta(tpl.doc_type).bg,
                color: docTypeMeta(tpl.doc_type).color,
              }"
            >
              {{ tpl.doc_type_label }}
            </span>
          </div>
          <div class="row-meta">
            <span>{{ tpl.var_keys?.length || 0 }} 个变量</span>
            <span class="dot">·</span>
            <span>{{ fmtDateTime(tpl.updated_at) }}</span>
          </div>
        </div>

        <el-empty
          v-if="!loading && !filtered.length"
          description="暂无模板"
          :image-size="80"
        />
      </el-scrollbar>

      <div class="side-foot">
        模板由全所共享，正文用 <code>{变量}</code> 占位，生成文书时自动填充。
      </div>
    </div>

    <!-- ============ 右：模板编辑 ============ -->
    <el-card v-if="editing" v-loading="detailLoading" shadow="never" class="tpl-edit">
      <template #header>
        <div class="edit-head">
          <span class="edit-title">{{ form.id ? '编辑模板' : '新建模板' }}</span>
          <div class="spacer" />
          <el-button size="small" plain @click="openPreview">
            <el-icon><View /></el-icon>预览
          </el-button>
          <el-button size="small" type="primary" :loading="saving" @click="save">
            <el-icon><Check /></el-icon>保存
          </el-button>
          <el-button v-if="form.id" size="small" link type="danger" @click="removeTemplate">
            删除
          </el-button>
        </div>
      </template>

      <div class="edit-meta">
        <div class="field">
          <label>模板名称</label>
          <el-input
            v-model="form.name"
            placeholder="如：民事起诉状（买卖纠纷）"
            maxlength="128"
            class="w320"
          />
        </div>

        <div class="field">
          <label>文书类型</label>
          <el-select v-model="form.doc_type" class="w150">
            <el-option
              v-for="t in docTypeOptions()"
              :key="t.value"
              :label="t.label"
              :value="t.value"
            />
          </el-select>
        </div>

        <div class="field">
          <label>插入变量</label>
          <el-dropdown trigger="click" max-height="320px" @command="insertVariable">
            <el-button plain size="default">
              <el-icon><Aim /></el-icon>选择变量<el-icon class="caret"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="v in variables"
                  :key="v.key"
                  :command="v.key"
                >
                  <span class="var-key">{{ '{' + v.key + '}' }}</span>
                  <span class="var-desc">{{ v.desc }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
          <span class="var-count">当前正文含 {{ currentVarKeys.length }} 个变量</span>
        </div>
      </div>

      <DocRichEditor
        ref="editorRef"
        v-model="form.content"
        height="calc(100vh - 350px)"
        placeholder="请输入模板正文，用 {客户姓名}、{案号} 等占位符标记需要自动填充的内容…"
      />
    </el-card>

    <!-- 未选择时 -->
    <el-card v-else shadow="never" class="tpl-empty-card">
      <div class="empty-box">
        <el-icon :size="34"><Collection /></el-icon>
        <p>从左侧选择一份模板进行编辑，或新建模板</p>
        <el-button type="primary" plain @click="startCreate">
          <el-icon><Plus /></el-icon>新建模板
        </el-button>
      </div>
    </el-card>

    <!-- 预览 -->
    <el-dialog v-model="previewVisible" title="模板预览" width="760px" top="6vh">
      <div class="preview-head">
        <span class="preview-name">{{ form.name || '未命名模板' }}</span>
        <span
          class="row-type"
          :style="{
            background: docTypeMeta(form.doc_type).bg,
            color: docTypeMeta(form.doc_type).color,
          }"
        >
          {{ docTypeMeta(form.doc_type).label }}
        </span>
      </div>
      <div class="preview-body">
        <div class="preview-doc" v-html="highlightVariables(form.content)" />
      </div>
      <template #footer>
        <span class="preview-tip">金色标签为待填充变量，生成文书时会替换为案件数据</span>
        <el-button @click="previewVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  Aim,
  ArrowDown,
  Check,
  Collection,
  Plus,
  Search,
  View,
} from '@element-plus/icons-vue'
import {
  createDocTemplate,
  deleteDocTemplate,
  getDocTemplate,
  listDocTemplates,
  listTemplateVariables,
  updateDocTemplate,
} from '@/api/documents'
import DocRichEditor from '@/components/DocRichEditor.vue'
import {
  docTypeOptions,
  ensureDocDicts,
  FALLBACK_VARIABLES,
  canonicalHtml,
  docTypeMeta,
  fmtDateTime,
  highlightVariables,
} from '@/utils/document'

// 文书类型下拉跟管理端字典走，setup 时拉一次
ensureDocDicts()

const loading = ref(false)
const detailLoading = ref(false)
const saving = ref(false)
const templates = ref([])
const variables = ref(FALLBACK_VARIABLES)
const keyword = ref('')
const typeFilter = ref('')
const editing = ref(false)
const previewVisible = ref(false)
const editorRef = ref(null)

const form = reactive({
  id: null,
  name: '',
  doc_type: 'complaint',
  content: '',
})

const snapshot = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim().toLowerCase()
  return templates.value.filter((t) => {
    if (typeFilter.value && t.doc_type !== typeFilter.value) return false
    if (kw && !t.name.toLowerCase().includes(kw)) return false
    return true
  })
})

const currentVarKeys = computed(() => {
  const keys = []
  const text = form.content || ''
  const regex = /\{([^{}\n]{1,20})\}/g
  let match = regex.exec(text)
  while (match) {
    const key = match[1].trim()
    if (!keys.includes(key)) keys.push(key)
    match = regex.exec(text)
  }
  return keys
})

// 正文按归一化 HTML 比较，编辑器改写字体内空格/分号不算修改
function formSnapshot() {
  return JSON.stringify({ ...form, content: canonicalHtml(form.content) })
}

const isDirty = computed(() => formSnapshot() !== snapshot.value)

function takeSnapshot() {
  snapshot.value = formSnapshot()
}

async function load() {
  loading.value = true
  try {
    const data = await listDocTemplates({ page: 1, page_size: 200 })
    templates.value = data.items || []
    if (!form.id && !editing.value && templates.value.length) {
      selectTemplate(templates.value[0], true)
    }
  } finally {
    loading.value = false
  }
}

async function loadVariables() {
  try {
    const data = await listTemplateVariables()
    if (Array.isArray(data) && data.length) variables.value = data
  } catch {
    variables.value = FALLBACK_VARIABLES
  }
}

async function confirmDiscard() {
  if (!editing.value || !isDirty.value) return true
  try {
    await ElMessageBox.confirm('当前模板有未保存的修改，确定放弃吗？', '未保存的修改', {
      type: 'warning',
      confirmButtonText: '放弃修改',
      cancelButtonText: '继续编辑',
    })
    return true
  } catch {
    return false
  }
}

async function selectTemplate(tpl, force = false) {
  if (!force) {
    const ok = await confirmDiscard()
    if (!ok) return
  }
  // 列表接口只返回摘要，正文需按 id 取详情
  detailLoading.value = true
  try {
    const detail = await getDocTemplate(tpl.id)
    form.id = detail.id
    form.name = detail.name
    form.doc_type = detail.doc_type
    form.content = detail.content || ''
    editing.value = true
    takeSnapshot()
  } finally {
    detailLoading.value = false
  }
}

async function startCreate() {
  const ok = await confirmDiscard()
  if (!ok) return
  form.id = null
  form.name = ''
  form.doc_type = typeFilter.value || 'complaint'
  form.content = '<p></p>'
  editing.value = true
  takeSnapshot()
}

function insertVariable(key) {
  editorRef.value?.insertText(`{${key}}`)
}

async function save() {
  if (!form.name.trim()) {
    ElMessage.warning('请填写模板名称')
    return
  }
  if (!form.content || !form.content.replace(/<[^>]+>/g, '').trim()) {
    ElMessage.warning('请填写模板正文')
    return
  }
  saving.value = true
  try {
    const payload = {
      name: form.name.trim(),
      doc_type: form.doc_type,
      content: form.content,
    }
    const saved = form.id
      ? await updateDocTemplate(form.id, payload)
      : await createDocTemplate(payload)
    ElMessage.success(form.id ? '模板已更新' : '模板已创建')
    form.id = saved.id
    form.name = saved.name
    form.doc_type = saved.doc_type
    form.content = saved.content
    takeSnapshot()
    await load()
  } finally {
    saving.value = false
  }
}

async function removeTemplate() {
  try {
    await ElMessageBox.confirm(
      `删除后不影响已生成的文书，确定删除模板「${form.name}」吗？`,
      '删除模板',
      { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  await deleteDocTemplate(form.id)
  ElMessage.success('模板已删除')
  editing.value = false
  form.id = null
  form.name = ''
  form.content = ''
  takeSnapshot()
  await load()
}

function openPreview() {
  if (!form.content) {
    ElMessage.warning('正文为空，暂无可预览内容')
    return
  }
  previewVisible.value = true
}

onMounted(() => {
  load()
  loadVariables()
})
</script>

<style scoped>
.tpl-manage {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  align-items: start;
}

/* ---------- 左侧列表 ---------- */
.tpl-side {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 14px 14px 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  height: calc(100vh - 108px);
}

.side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.side-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.tpl-scroll {
  flex: 1;
  min-height: 0;
}

.tpl-row {
  border: 1px solid transparent;
  border-bottom-color: var(--brand-line);
  padding: 10px 8px;
  cursor: pointer;
  transition: background 0.15s;
  border-radius: 8px;
}

.tpl-row:hover {
  background: #fafbfd;
}

.tpl-row.active {
  background: #fdfaf3;
  border-color: var(--brand-gold-light);
}

.row-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.row-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.row-type {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  flex-shrink: 0;
}

.row-meta {
  margin-top: 4px;
  font-size: 11px;
  color: var(--brand-muted);
  display: flex;
  gap: 6px;
}

.dot {
  color: #c6ccd8;
}

.side-foot {
  border-top: 1px dashed var(--brand-line);
  padding-top: 10px;
  font-size: 11px;
  color: var(--brand-muted);
  line-height: 1.8;
}

.side-foot code {
  background: #f4f5f8;
  padding: 0 4px;
  border-radius: 3px;
  color: var(--brand-gold-deep);
}

/* ---------- 右侧编辑 ---------- */
.tpl-edit {
  border-radius: 12px;
  border: 1px solid var(--brand-line);
}

.tpl-edit :deep(.el-card__body) {
  padding: 14px 16px 16px;
}

.edit-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.edit-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.spacer {
  flex: 1;
}

.edit-meta {
  display: flex;
  align-items: center;
  gap: 20px;
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

.field label {
  font-size: 12px;
  color: var(--brand-muted);
  white-space: nowrap;
}

.w320 {
  width: 320px;
}

.w150 {
  width: 150px;
}

.caret {
  margin-left: 2px;
}

.var-key {
  font-family: 'SFMono-Regular', Consolas, monospace;
  color: var(--brand-gold-deep);
  font-size: 12px;
}

.var-desc {
  margin-left: 10px;
  font-size: 11px;
  color: var(--brand-muted);
}

.var-count {
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------- 空态 ---------- */
.tpl-empty-card {
  border-radius: 12px;
  border: 1px solid var(--brand-line);
  min-height: 420px;
}

.empty-box {
  min-height: 380px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 10px;
  color: var(--brand-muted);
  font-size: 13px;
}

.empty-box p {
  margin: 0;
}

/* ---------- 预览 ---------- */
.preview-head {
  display: flex;
  align-items: center;
  gap: 10px;
  padding-bottom: 10px;
  border-bottom: 1px dashed var(--brand-line);
  margin-bottom: 14px;
}

.preview-name {
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-ink);
}

.preview-body {
  max-height: 56vh;
  overflow-y: auto;
  background: #fbfbfd;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 18px 22px;
}

.preview-doc {
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
  font-size: 14px;
  line-height: 2;
  color: var(--brand-text);
}

.preview-doc :deep(p) {
  margin: 0 0 6px;
}

.preview-tip {
  float: left;
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 32px;
}

@media (max-width: 1200px) {
  .tpl-manage {
    grid-template-columns: 1fr;
  }

  .tpl-side {
    height: auto;
    max-height: 380px;
  }
}
</style>
