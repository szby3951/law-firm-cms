<template>
  <el-dialog
    :model-value="modelValue"
    title="从模板生成文书"
    width="920px"
    top="6vh"
    :close-on-click-modal="false"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @open="onOpen"
  >
    <div class="gen-body">
      <!-- 左：模板列表 -->
      <div class="tpl-pane">
        <el-input
          v-model="tplKeyword"
          placeholder="搜索模板名称"
          clearable
          size="default"
          class="tpl-search"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <div class="type-tabs">
          <button
            v-for="t in typeTabs"
            :key="t.value"
            class="type-tab"
            :class="{ active: tplType === t.value }"
            @click="tplType = t.value"
          >
            {{ t.label }}
          </button>
        </div>

        <el-scrollbar v-loading="loadingTemplates" class="tpl-scroll">
          <div
            v-for="tpl in filteredTemplates"
            :key="tpl.id"
            class="tpl-item"
            :class="{ active: tpl.id === selectedId }"
            @click="selectTemplate(tpl)"
          >
            <div class="tpl-head">
              <span class="tpl-name">{{ tpl.name }}</span>
              <span
                class="tpl-type"
                :style="{
                  background: docTypeMeta(tpl.doc_type).bg,
                  color: docTypeMeta(tpl.doc_type).color,
                }"
              >
                {{ tpl.doc_type_label }}
              </span>
            </div>
            <div class="tpl-excerpt">{{ tpl.excerpt || '暂无正文摘要' }}</div>
            <div class="tpl-foot">
              <span>{{ tpl.var_keys?.length || 0 }} 个变量</span>
            </div>
          </div>

          <el-empty
            v-if="!loadingTemplates && !filteredTemplates.length"
            description="没有匹配的模板"
            :image-size="80"
          />
        </el-scrollbar>
      </div>

      <!-- 右：填充参数 + 预览 -->
      <div class="form-pane">
        <div class="form-row">
          <label class="form-label">关联案件</label>
          <el-select
            v-model="caseId"
            placeholder="选择案件后自动填充客户、案号、法院等字段"
            clearable
            filterable
            class="form-control"
            @change="preview = null"
          >
            <el-option
              v-for="c in caseOptions"
              :key="c.id"
              :label="`${c.case_no} · ${c.title}`"
              :value="c.id"
            />
          </el-select>
        </div>

        <div class="form-row">
          <label class="form-label">文书标题</label>
          <el-input
            v-model="title"
            placeholder="留空则按「客户姓名 + 模板名称」自动生成"
            class="form-control"
            maxlength="255"
            @input="preview = null"
          />
        </div>

        <div class="preview-head">
          <span class="preview-title">填充预览</span>
          <div class="spacer" />
          <el-button size="small" :loading="generating" @click="doGenerate">
            <el-icon><Refresh /></el-icon>重新生成
          </el-button>
        </div>

        <div class="preview-box" v-loading="generating">
          <template v-if="preview">
            <div class="preview-badges">
              <span class="badge ok">已填充 {{ Object.keys(preview.filled).length }} 个变量</span>
              <span v-if="preview.missing.length" class="badge warn">
                {{ preview.missing.length }} 个变量未取到值：{{ preview.missing.join('、') }}
              </span>
            </div>
            <div class="preview-doc" v-html="highlightVariables(preview.content)" />
          </template>
          <div v-else class="preview-empty">
            <el-icon :size="26"><Document /></el-icon>
            <p>选择模板并点击「生成预览」，确认填充结果后再进入编辑器</p>
          </div>
        </div>
      </div>
    </div>

    <template #footer>
      <el-button @click="emit('update:modelValue', false)">取消</el-button>
      <el-button type="primary" :loading="generating" @click="startEdit">
        <el-icon><EditPen /></el-icon>生成并编辑
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  Document,
  EditPen,
  Refresh,
  Search,
} from '@element-plus/icons-vue'
import { generateDocument, listDocTemplates } from '@/api/documents'
import {
  docTypeOptions,
  ensureDocDicts,
  docTypeMeta,
  highlightVariables,
} from '@/utils/document'

// 文书类型下拉跟管理端字典走，setup 时拉一次
ensureDocDicts()

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  caseOptions: { type: Array, default: () => [] },
})

const emit = defineEmits(['update:modelValue', 'open'])

const loadingTemplates = ref(false)
const generating = ref(false)
const templates = ref([])
const tplKeyword = ref('')
const tplType = ref('')
const selectedId = ref(null)
const caseId = ref('')
const title = ref('')
const preview = ref(null)

const typeTabs = computed(() => [{ value: '', label: '全部' }, ...docTypeOptions()])

const filteredTemplates = computed(() => {
  const kw = tplKeyword.value.trim().toLowerCase()
  return templates.value.filter((t) => {
    if (tplType.value && t.doc_type !== tplType.value) return false
    if (kw && !t.name.toLowerCase().includes(kw)) return false
    return true
  })
})

const selectedTemplate = computed(
  () => templates.value.find((t) => t.id === selectedId.value) || null,
)

async function loadTemplates() {
  loadingTemplates.value = true
  try {
    const data = await listDocTemplates({ page: 1, page_size: 200 })
    templates.value = data.items || []
  } finally {
    loadingTemplates.value = false
  }
}

function onOpen() {
  if (!templates.value.length) loadTemplates()
  preview.value = null
  selectedId.value = null
  caseId.value = ''
  title.value = ''
  tplKeyword.value = ''
  tplType.value = ''
}

function selectTemplate(tpl) {
  selectedId.value = tpl.id
  preview.value = null
}

async function doGenerate() {
  if (!selectedId.value) {
    ElMessage.warning('请先选择一份模板')
    return null
  }
  generating.value = true
  try {
    const data = await generateDocument({
      template_id: selectedId.value,
      case_id: caseId.value || null,
      title: title.value.trim() || null,
    })
    preview.value = data
    if (!title.value) title.value = data.title
    return data
  } catch {
    return null
  } finally {
    generating.value = false
  }
}

async function startEdit() {
  let data = preview.value
  if (!data) data = await doGenerate()
  if (!data) return
  emit('open', {
    template_id: data.template_id,
    case_id: data.case_id,
    title: data.title,
  })
}
</script>

<style scoped>
.gen-body {
  display: grid;
  grid-template-columns: 340px 1fr;
  gap: 18px;
  height: 58vh;
  min-height: 420px;
}

/* ---------- 模板列表 ---------- */
.tpl-pane {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-height: 0;
  border-right: 1px solid var(--brand-line);
  padding-right: 16px;
}

.tpl-search {
  flex-shrink: 0;
}

.type-tabs {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  flex-shrink: 0;
}

.type-tab {
  border: 1px solid var(--brand-line);
  background: #fff;
  color: var(--brand-text);
  font-size: 12px;
  padding: 2px 9px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.type-tab:hover {
  border-color: var(--brand-gold);
  color: var(--brand-gold-deep);
}

.type-tab.active {
  background: var(--brand-navy);
  border-color: var(--brand-navy);
  color: #fff;
}

.tpl-scroll {
  flex: 1;
  min-height: 0;
}

.tpl-item {
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s;
  background: #fff;
}

.tpl-item:hover {
  border-color: var(--brand-gold-light);
  box-shadow: 0 2px 8px rgba(20, 33, 61, 0.06);
}

.tpl-item.active {
  border-color: var(--brand-gold);
  background: #fdfaf3;
}

.tpl-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.tpl-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.tpl-type {
  font-size: 11px;
  line-height: 18px;
  padding: 0 6px;
  border-radius: 9px;
  flex-shrink: 0;
}

.tpl-excerpt {
  margin-top: 4px;
  font-size: 12px;
  color: var(--brand-muted);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.tpl-foot {
  margin-top: 4px;
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------- 参数与预览 ---------- */
.form-pane {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-height: 0;
}

.form-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.form-label {
  width: 64px;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--brand-ink);
}

.form-control {
  flex: 1;
}

.preview-head {
  display: flex;
  align-items: center;
  margin-top: 2px;
}

.preview-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
}

.spacer {
  flex: 1;
}

.preview-box {
  flex: 1;
  min-height: 0;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  background: #fbfbfd;
  padding: 12px 14px;
  overflow-y: auto;
}

.preview-badges {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.badge {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 10px;
}

.badge.ok {
  background: #e8f4ef;
  color: #1f5f4a;
}

.badge.warn {
  background: #fbf3e2;
  color: #a5813d;
}

.preview-doc {
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
  font-size: 14px;
  line-height: 1.9;
  color: var(--brand-text);
}

.preview-doc :deep(p) {
  margin: 0 0 6px;
}

.preview-doc :deep(h1),
.preview-doc :deep(h2),
.preview-doc :deep(h3) {
  font-size: 15px;
  margin: 10px 0 6px;
  color: var(--brand-ink);
}

.preview-empty {
  height: 100%;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  color: var(--brand-muted);
  font-size: 13px;
  text-align: center;
}

.preview-empty p {
  margin: 0;
  max-width: 320px;
  line-height: 1.7;
}
</style>
