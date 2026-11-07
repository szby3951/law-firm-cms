<template>
  <el-dialog
    :model-value="modelValue"
    title="案件立案"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-form-item label="委托客户" prop="client_id">
        <el-select
          v-model="form.client_id"
          placeholder="选择委托客户"
          filterable
          remote
          :remote-method="searchClients"
          :loading="clientLoading"
          style="width: 100%"
        >
          <el-option
            v-for="c in clientOptions"
            :key="c.id"
            :label="`${c.name}（${c.phone || '无电话'}）`"
            :value="c.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="案件标题" prop="title">
        <el-input v-model="form.title" placeholder="如：张三诉李四合同纠纷案" maxlength="255" />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="案由" prop="case_cause">
            <el-select
              v-model="form.case_cause"
              placeholder="选择或输入案由"
              filterable
              allow-create
              default-first-option
              clearable
              style="width: 100%"
            >
              <el-option
                v-for="o in causeOptions"
                :key="o.value"
                :label="o.label"
                :value="o.label"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="案件类型" prop="case_type">
            <el-radio-group v-model="form.case_type">
              <el-radio-button value="litigation">诉讼</el-radio-button>
              <el-radio-button value="non_litigation">非诉</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="受理法院" prop="court">
            <el-input v-model="form.court" placeholder="受理法院 / 机构" maxlength="255" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="对方当事人" prop="opposing_party">
            <el-input v-model="form.opposing_party" placeholder="对方当事人姓名" maxlength="255" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="标的额" prop="amount">
        <el-input-number
          v-model="form.amount"
          :min="0"
          :max="9999999999.99"
          :precision="2"
          :step="10000"
          :controls="false"
          placeholder="0.00"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="案情描述" prop="description">
        <el-input v-model="form.description" type="textarea" :rows="3" placeholder="简要描述案情（选填）" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">提交立案</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createCase } from '@/api/cases'
import { listClients } from '@/api/clients'
import { useDictStore } from '@/stores/dict'

const emit = defineEmits(['update:modelValue', 'saved'])

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 从客户详情页立案时预置委托客户，避免重复搜索
  clientId: { type: Number, default: null },
  clientName: { type: String, default: '' },
})

const formRef = ref()
const submitting = ref(false)
const clientLoading = ref(false)
const clientOptions = ref([])

// 案由候选来自管理端字典；允许手工输入，兼容字典里没有的新案由
const dictStore = useDictStore()
const causeOptions = computed(() => dictStore.options('case_cause'))
dictStore.ensure()

const emptyForm = () => ({
  client_id: null,
  title: '',
  case_cause: '',
  case_type: 'litigation',
  court: '',
  opposing_party: '',
  amount: 0,
  description: '',
})

const form = reactive(emptyForm())

const rules = {
  client_id: [{ required: true, message: '请选择委托客户', trigger: 'change' }],
  title: [
    { required: true, message: '请输入案件标题', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v && v.trim()) return cb()
        cb(new Error('案件标题不能为空'))
      },
      trigger: 'blur',
    },
  ],
  case_cause: [{ max: 64, message: '案由不能超过 64 个字符', trigger: 'blur' }],
  court: [{ max: 255, message: '受理法院不能超过 255 个字符', trigger: 'blur' }],
  opposing_party: [{ max: 255, message: '对方当事人不能超过 255 个字符', trigger: 'blur' }],
  amount: [
    { required: true, message: '请输入标的额', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v == null || v === '') return cb(new Error('请输入标的额'))
        if (v < 0) return cb(new Error('标的额不能为负数'))
        if (v > 9999999999.99) return cb(new Error('标的额不能超过 9999999999.99 元'))
        cb()
      },
      trigger: 'blur',
    },
  ],
}

async function searchClients(keyword) {
  clientLoading.value = true
  try {
    const data = await listClients({ keyword, page: 1, page_size: 50 })
    clientOptions.value = data.items
  } finally {
    clientLoading.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  Object.assign(form, emptyForm())
}

// 预置客户：先塞进下拉选项，保证选中值有对应 label；再补拉一批常用客户
function presetClient() {
  if (!props.clientId) return
  form.client_id = props.clientId
  const name = props.clientName || `客户 #${props.clientId}`
  if (!clientOptions.value.some((c) => c.id === props.clientId)) {
    clientOptions.value = [{ id: props.clientId, name, phone: '' }, ...clientOptions.value]
  }
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = { ...form }
    const created = await createCase(payload)
    ElMessage.success(`立案成功，案号 ${created.case_no}`)
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}

// 打开弹窗时预加载一批客户，避免空白；带 clientId 时同步预置该客户
watch(
  () => props.modelValue,
  async (v) => {
    if (!v) return
    presetClient()
    await searchClients('')
    // 接口结果会覆盖选项列表，预置项不在其中时补回，避免下拉只显示客户 ID
    presetClient()
  },
)
</script>

<style scoped>
:deep(.el-select) {
  width: 100%;
}
</style>
