<template>
  <div class="settings">
    <el-tabs v-model="tab" class="tabs">
      <!-- ================= 数据字典 ================= -->
      <el-tab-pane label="数据字典" name="dict">
        <div class="pane">
          <div class="policy-tip">
            <el-icon class="policy-icon"><InfoFilled /></el-icon>
            <span>
              字典是各业务表单下拉的候选来源。修改后新表单立即可选，
              <b>已保存的历史记录不受影响</b>。
            </span>
          </div>

          <div class="dict-body">
            <!-- 分类 -->
            <div class="type-list">
              <div class="type-title">分类</div>
              <div
                v-for="t in types"
                :key="t.dict_type"
                class="type-item"
                :class="{ active: activeType === t.dict_type }"
                @click="switchType(t.dict_type)"
              >
                <span class="type-name">{{ typeLabel(t.dict_type) }}</span>
                <span class="type-count">{{ t.count }}</span>
              </div>
              <div v-if="!types.length && !dictLoading" class="type-empty">暂无字典</div>
            </div>

            <!-- 条目 -->
            <div class="dict-main">
              <div class="bar">
                <div class="bar-title">
                  {{ typeLabel(activeType) }}
                  <span class="bar-sub">{{ items.length }} 项</span>
                </div>
                <div class="spacer" />
                <el-button type="primary" size="default" @click="openCreate">
                  <el-icon><Plus /></el-icon>新增条目
                </el-button>
              </div>

              <el-table :data="items" v-loading="dictLoading" stripe style="width: 100%">
                <el-table-column prop="label" label="显示文本" min-width="160" />
                <el-table-column prop="value" label="存储值" min-width="180">
                  <template #default="{ row }">
                    <span class="mono">{{ row.value }}</span>
                  </template>
                </el-table-column>
                <el-table-column prop="sort" label="排序" width="90" align="center" />
                <el-table-column label="操作" width="140" align="center">
                  <template #default="{ row }">
                    <el-button link type="primary" size="small" @click="openEdit(row)">
                      编辑
                    </el-button>
                    <el-button link type="danger" size="small" @click="removeItem(row)">
                      删除
                    </el-button>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </el-tab-pane>

      <!-- ================= 律所信息 ================= -->
      <el-tab-pane label="律所信息" name="firm">
        <div class="pane narrow">
          <div class="policy-tip">
            <el-icon class="policy-icon"><InfoFilled /></el-icon>
            <span>
              律所名称会写入 AI 系统提示词（「你是<b>XX律所</b>的法律顾问」），保存后立即生效。
            </span>
          </div>

          <el-card shadow="never" class="form-card">
            <el-form ref="firmRef" :model="firm" :rules="firmRules" label-width="96px" v-loading="firmLoading">
              <el-form-item label="律所名称" prop="name">
                <el-input v-model="firm.name" maxlength="128" placeholder="如：金诚律师事务所" />
              </el-form-item>
              <el-form-item label="Logo 地址" prop="logo">
                <el-input v-model="firm.logo" maxlength="255" placeholder="选填，图片 URL" />
              </el-form-item>
              <el-form-item label="联系地址" prop="address">
                <el-input v-model="firm.address" maxlength="255" placeholder="选填" />
              </el-form-item>
              <el-form-item label="联系电话" prop="phone">
                <el-input v-model="firm.phone" maxlength="32" placeholder="选填" />
              </el-form-item>
              <el-form-item label="律所简介" prop="intro">
                <el-input
                  v-model="firm.intro"
                  type="textarea"
                  :rows="4"
                  maxlength="2000"
                  show-word-limit
                  placeholder="选填，用于对外展示"
                />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="firmSaving" @click="saveFirm">保存</el-button>
                <span class="save-hint" v-if="firmUpdatedAt">上次更新：{{ firmUpdatedAt }}</span>
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </el-tab-pane>

      <!-- ================= AI 配置 ================= -->
      <el-tab-pane label="AI 配置" name="ai">
        <div class="pane narrow">
          <el-card shadow="never" class="ai-status">
            <div class="status-row">
              <div class="status-item">
                <span class="status-label">当前生效</span>
                <el-tag :type="ai.active_source === 'db' ? 'success' : 'info'" effect="plain" size="small">
                  {{ ai.active_source === 'db' ? '数据库配置' : '.env 配置' }}
                </el-tag>
              </div>
              <div class="status-item">
                <span class="status-label">对话模型</span>
                <span class="mono strong">{{ ai.active_model || '—' }}</span>
              </div>
              <div class="status-item">
                <span class="status-label">API Key</span>
                <span class="mono">{{ ai.api_key_set ? ai.api_key_masked : '未配置' }}</span>
              </div>
            </div>
            <div class="status-tip">
              启用数据库配置后，对话模型改走此处设置；关闭则回滚到 .env。
              嵌入模型（向量化）由服务端 .env 决定，此处仅作记录，运行期不切换。
            </div>
          </el-card>

          <el-card shadow="never" class="form-card">
            <el-form ref="aiRef" :model="aiForm" :rules="aiRules" label-width="110px" v-loading="aiLoading">
              <el-form-item label="启用数据库配置">
                <el-switch v-model="aiForm.status" :active-value="1" :inactive-value="0" />
                <span class="switch-tip">开启后优先于 .env，保存即生效</span>
              </el-form-item>
              <el-form-item label="供应商" prop="provider">
                <el-input v-model="aiForm.provider" maxlength="32" placeholder="deepseek / qwen / openai" />
              </el-form-item>
              <el-form-item label="接口地址" prop="base_url">
                <el-input v-model="aiForm.base_url" maxlength="255" placeholder="https://api.deepseek.com/v1" />
              </el-form-item>
              <el-form-item label="对话模型" prop="model">
                <el-input v-model="aiForm.model" maxlength="64" placeholder="deepseek-chat" />
              </el-form-item>
              <el-form-item label="API Key" prop="api_key">
                <el-input
                  v-model="aiForm.api_key"
                  type="password"
                  show-password
                  maxlength="255"
                  :placeholder="ai.api_key_set ? `已配置（${ai.api_key_masked}），留空表示不修改` : '尚未配置，启用前必须填写'"
                />
              </el-form-item>
              <el-form-item label="采样温度" prop="temperature">
                <el-input-number v-model="aiForm.temperature" :min="0" :max="2" :step="0.1" :precision="2" />
                <span class="switch-tip">越低越稳定，法律问答建议 0.1~0.4</span>
              </el-form-item>
              <el-form-item label="嵌入模型">
                <el-input v-model="aiForm.embedding_model" maxlength="64" placeholder="仅记录，不参与运行" />
              </el-form-item>
              <el-form-item>
                <el-button type="primary" :loading="aiSaving" @click="saveAi">保存并应用</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </div>
      </el-tab-pane>
    </el-tabs>

    <!-- 字典项编辑弹窗 -->
    <el-dialog
      v-model="dictVisible"
      :title="dictForm.id ? '编辑字典项' : '新增字典项'"
      width="460px"
      @closed="resetDictForm"
    >
      <el-form ref="dictRef" :model="dictForm" :rules="dictRules" label-width="86px">
        <el-form-item label="分类" prop="dict_type">
          <el-select
            v-model="dictForm.dict_type"
            filterable
            allow-create
            default-first-option
            placeholder="选择或输入分类"
            style="width: 100%"
          >
            <el-option
              v-for="t in types"
              :key="t.dict_type"
              :label="`${typeLabel(t.dict_type)}（${t.dict_type}）`"
              :value="t.dict_type"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="显示文本" prop="label">
          <el-input v-model="dictForm.label" maxlength="64" placeholder="下拉里看到的文字" />
        </el-form-item>
        <el-form-item label="存储值" prop="value">
          <el-input v-model="dictForm.value" maxlength="64" placeholder="入库的值，字母/数字/下划线" />
        </el-form-item>
        <el-form-item label="排序" prop="sort">
          <el-input-number v-model="dictForm.sort" :min="0" :max="9999" :step="10" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dictVisible = false">取消</el-button>
        <el-button type="primary" :loading="dictSaving" @click="saveDict">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { InfoFilled, Plus } from '@element-plus/icons-vue'
import {
  createDict,
  deleteDict,
  getAiConfig,
  getFirm,
  listDicts,
  updateAiConfig,
  updateDict,
  updateFirm,
} from '@/api/settings'

// 分类中文名；未登记的分类直接显示 key，方便管理员自定义扩展
const TYPE_LABELS = {
  case_cause: '案由',
  contract_type: '合同类型',
  doc_type: '文书类型',
  source_channel: '来源渠道',
}

const tab = ref('dict')

// 支持 ?tab=firm / ?tab=ai 直达，便于从其它页面跳转定位
const TAB_NAMES = ['dict', 'firm', 'ai']
const routeTab = useRoute().query.tab
if (TAB_NAMES.includes(routeTab)) tab.value = routeTab

function typeLabel(key) {
  return TYPE_LABELS[key] || key || '未分类'
}

/* ---------------- 字典 ---------------- */
const types = ref([])
const items = ref([])
const activeType = ref('')
const dictLoading = ref(false)
const dictVisible = ref(false)
const dictSaving = ref(false)
const dictRef = ref(null)
const dictForm = reactive({ id: null, dict_type: '', label: '', value: '', sort: 0 })

const dictRules = {
  dict_type: [{ required: true, message: '请选择分类', trigger: 'change' }],
  label: [{ required: true, message: '请输入显示文本', trigger: 'blur' }],
  value: [
    { required: true, message: '请输入存储值', trigger: 'blur' },
    { pattern: /^[A-Za-z0-9_-]{1,64}$/, message: '只能包含字母、数字、下划线与连字符', trigger: 'blur' },
  ],
}

async function loadDicts(dictType) {
  dictLoading.value = true
  try {
    // 不指定分类时先取分类汇总，再加载第一个分类的条目
    if (!dictType) {
      const meta = await listDicts({})
      types.value = meta.types || []
      const first = types.value[0]?.dict_type
      if (!first) {
        items.value = []
        activeType.value = ''
        return
      }
      dictType = first
    }
    const data = await listDicts({ dict_type: dictType })
    types.value = data.types || types.value
    items.value = data.items || []
    activeType.value = dictType
  } finally {
    dictLoading.value = false
  }
}

function switchType(key) {
  if (key === activeType.value) return
  activeType.value = key
  loadDicts(key)
}

function openCreate() {
  dictForm.id = null
  dictForm.dict_type = activeType.value
  dictForm.label = ''
  dictForm.value = ''
  dictForm.sort = (items.value.at(-1)?.sort || 0) + 10
  dictVisible.value = true
}

function openEdit(row) {
  Object.assign(dictForm, {
    id: row.id,
    dict_type: row.dict_type,
    label: row.label,
    value: row.value,
    sort: row.sort,
  })
  dictVisible.value = true
}

function resetDictForm() {
  dictRef.value?.clearValidate()
}

async function saveDict() {
  await dictRef.value?.validate()
  dictSaving.value = true
  try {
    const payload = {
      dict_type: dictForm.dict_type,
      label: dictForm.label.trim(),
      value: dictForm.value.trim(),
      sort: dictForm.sort,
    }
    if (dictForm.id) {
      await updateDict(dictForm.id, payload)
      ElMessage.success('已保存')
    } else {
      await createDict(payload)
      ElMessage.success('已新增')
    }
    dictVisible.value = false
    activeType.value = payload.dict_type
    await loadDicts(payload.dict_type)
  } finally {
    dictSaving.value = false
  }
}

async function removeItem(row) {
  await ElMessageBox.confirm(
    `删除「${row.label}」后，新建表单将不再出现该选项，历史数据不受影响。确定删除？`,
    '删除字典项',
    { type: 'warning', confirmButtonText: '确定删除' }
  )
  await deleteDict(row.id)
  ElMessage.success('已删除')
  await loadDicts(activeType.value)
}

/* ---------------- 律所信息 ---------------- */
const firmRef = ref(null)
const firm = reactive({ name: '', logo: '', address: '', phone: '', intro: '' })
const firmLoading = ref(false)
const firmSaving = ref(false)
const firmUpdatedAt = ref('')

const firmRules = {
  name: [{ required: true, message: '请输入律所名称', trigger: 'blur' }],
}

async function loadFirm() {
  firmLoading.value = true
  try {
    const data = await getFirm()
    Object.assign(firm, {
      name: data.name || '',
      logo: data.logo || '',
      address: data.address || '',
      phone: data.phone || '',
      intro: data.intro || '',
    })
    firmUpdatedAt.value = (data.updated_at || '').replace('T', ' ').slice(0, 16)
  } finally {
    firmLoading.value = false
  }
}

async function saveFirm() {
  await firmRef.value?.validate()
  firmSaving.value = true
  try {
    const data = await updateFirm({
      name: firm.name.trim(),
      logo: firm.logo.trim() || null,
      address: firm.address.trim() || null,
      phone: firm.phone.trim() || null,
      intro: firm.intro.trim() || null,
    })
    firmUpdatedAt.value = (data.updated_at || '').replace('T', ' ').slice(0, 16)
    ElMessage.success('已保存，AI 提示词中的律所名称同步更新')
  } finally {
    firmSaving.value = false
  }
}

/* ---------------- AI 配置 ---------------- */
const aiRef = ref(null)
const ai = reactive({ active_model: '', active_source: 'env', api_key_set: false, api_key_masked: '' })
const aiForm = reactive({
  provider: '',
  base_url: '',
  model: '',
  api_key: '',
  temperature: 0.3,
  embedding_model: '',
  status: 0,
})
const aiLoading = ref(false)
const aiSaving = ref(false)

const aiRules = {
  provider: [{ required: true, message: '请输入供应商标识', trigger: 'blur' }],
  base_url: [
    { required: true, message: '请输入接口地址', trigger: 'blur' },
    { pattern: /^https?:\/\//, message: '需以 http:// 或 https:// 开头', trigger: 'blur' },
  ],
  model: [{ required: true, message: '请输入对话模型', trigger: 'blur' }],
}

function fillAi(data) {
  ai.active_model = data.active_model
  ai.active_source = data.active_source
  ai.api_key_set = data.api_key_set
  ai.api_key_masked = data.api_key_masked
  Object.assign(aiForm, {
    provider: data.provider,
    base_url: data.base_url,
    model: data.model,
    api_key: '',
    temperature: Number(data.temperature ?? 0.3),
    embedding_model: data.embedding_model || '',
    status: data.status,
  })
}

async function loadAi() {
  aiLoading.value = true
  try {
    fillAi(await getAiConfig())
  } finally {
    aiLoading.value = false
  }
}

async function saveAi() {
  await aiRef.value?.validate()
  if (aiForm.status === 1 && !aiForm.api_key && !ai.api_key_set) {
    ElMessage.warning('启用数据库配置前请先填写 API Key')
    return
  }
  aiSaving.value = true
  try {
    const data = await updateAiConfig({
      provider: aiForm.provider.trim(),
      base_url: aiForm.base_url.trim(),
      model: aiForm.model.trim(),
      api_key: aiForm.api_key.trim() || null,
      temperature: aiForm.temperature,
      embedding_model: aiForm.embedding_model.trim() || null,
      status: aiForm.status,
    })
    fillAi(data)
    ElMessage.success(
      data.active_source === 'db' ? '已保存，当前使用数据库配置' : '已保存，当前使用 .env 配置'
    )
  } finally {
    aiSaving.value = false
  }
}

onMounted(async () => {
  await loadDicts('')
  await loadFirm()
  await loadAi()
})
</script>

<style scoped>
.settings {
  display: flex;
  flex-direction: column;
}

.tabs :deep(.el-tabs__header) {
  margin-bottom: 16px;
}

.pane {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.pane.narrow {
  max-width: 760px;
}

/* 口径说明条：与账号管理页一致 */
.policy-tip {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 11px 14px;
  border-radius: 10px;
  border-left: 3px solid var(--brand-gold);
  background: linear-gradient(90deg, rgba(201, 165, 92, 0.09), rgba(201, 165, 92, 0.03));
  font-size: 13px;
  line-height: 1.65;
  color: var(--brand-text);
}

.policy-tip b {
  font-weight: 600;
  color: var(--brand-ink);
}

.policy-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--brand-gold-deep);
  font-size: 15px;
}

/* ---------- 字典布局 ---------- */
.dict-body {
  display: flex;
  gap: 16px;
  align-items: flex-start;
}

.type-list {
  width: 200px;
  flex-shrink: 0;
  background: #fff;
  border-radius: 12px;
  padding: 10px;
  box-shadow: 0 1px 3px rgba(20, 30, 55, 0.06);
}

.type-title {
  font-size: 12px;
  color: var(--brand-muted);
  letter-spacing: 1px;
  padding: 4px 10px 8px;
}

.type-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 9px 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 13px;
  color: var(--brand-text);
  transition: background 0.15s;
}

.type-item:hover {
  background: rgba(26, 43, 74, 0.05);
}

.type-item.active {
  background: linear-gradient(90deg, rgba(26, 43, 74, 0.08), rgba(201, 165, 92, 0.08));
  color: var(--brand-ink);
  font-weight: 600;
}

.type-count {
  font-size: 12px;
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

.type-empty {
  padding: 12px 10px;
  font-size: 12px;
  color: var(--brand-muted);
}

.dict-main {
  flex: 1;
  min-width: 0;
  background: #fff;
  border-radius: 12px;
  padding: 14px 16px 8px;
  box-shadow: 0 1px 3px rgba(20, 30, 55, 0.06);
}

.bar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 10px;
}

.bar-title {
  font-weight: 600;
  color: var(--brand-ink);
}

.bar-sub {
  margin-left: 8px;
  font-size: 12px;
  font-weight: 400;
  color: var(--brand-muted);
}

.spacer {
  flex: 1;
}

.mono {
  font-variant-numeric: tabular-nums;
  font-family: 'SFMono-Regular', Consolas, monospace;
  font-size: 12.5px;
}

.strong {
  font-weight: 600;
  color: var(--brand-ink);
}

/* ---------- 表单 ---------- */
.form-card {
  border-radius: 12px;
}

.save-hint {
  margin-left: 12px;
  font-size: 12px;
  color: var(--brand-muted);
}

.switch-tip {
  margin-left: 10px;
  font-size: 12px;
  color: var(--brand-muted);
}

.ai-status {
  border-radius: 12px;
  border-left: 3px solid var(--brand-gold);
}

.ai-status :deep(.el-card__body) {
  padding: 14px 16px;
}

.status-row {
  display: flex;
  flex-wrap: wrap;
  gap: 28px;
}

.status-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.status-label {
  font-size: 12px;
  color: var(--brand-muted);
}

.status-tip {
  margin-top: 10px;
  font-size: 12px;
  line-height: 1.6;
  color: var(--brand-muted);
}

@media (max-width: 1100px) {
  .dict-body {
    flex-direction: column;
  }
  .type-list {
    width: 100%;
  }
  .type-item {
    display: inline-flex;
    margin-right: 6px;
  }
}
</style>
