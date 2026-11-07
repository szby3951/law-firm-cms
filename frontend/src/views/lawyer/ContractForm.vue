<template>
  <el-dialog
    :model-value="modelValue"
    :title="contract ? '编辑合同' : '新建合同'"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-form-item label="合同名称" prop="name">
        <el-input v-model="form.name" placeholder="如：XX 委托代理合同" maxlength="255" />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="委托客户" prop="client_id">
            <el-select
              v-model="form.client_id"
              placeholder="选择客户"
              filterable
              remote
              :remote-method="searchClients"
              :loading="clientLoading"
              :disabled="!!contract"
              style="width: 100%"
              @change="onClientChange"
            >
              <el-option
                v-for="c in clientOptions"
                :key="c.id"
                :label="`${c.name}（${c.phone || '无电话'}）`"
                :value="c.id"
              />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="合同类型" prop="contract_type">
            <el-select v-model="form.contract_type" placeholder="选择类型" clearable style="width: 100%">
              <el-option
                v-for="o in typeOptions"
                :key="o.value"
                :label="o.label"
                :value="o.value"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="关联案件" prop="case_id">
        <el-select
          v-model="form.case_id"
          placeholder="选择关联案件（可选）"
          filterable
          clearable
          :loading="caseLoading"
          style="width: 100%"
        >
          <el-option
            v-for="c in caseOptions"
            :key="c.id"
            :label="`${c.case_no} · ${c.title}`"
            :value="c.id"
          />
        </el-select>
      </el-form-item>

      <el-form-item label="合同金额" prop="amount">
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

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="生效日期" prop="start_date">
            <el-date-picker
              v-model="form.start_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择生效日期"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="到期日期" prop="end_date">
            <el-date-picker
              v-model="form.end_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="选择到期日期"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="合同状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio-button v-for="(m, k) in statusMeta" :key="k" :value="k">{{ m.label }}</el-radio-button>
        </el-radio-group>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ contract ? '保存修改' : '创建合同' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createContract, updateContract } from '@/api/contracts'
import { listClients } from '@/api/clients'
import { listCases } from '@/api/cases'
import { useDictStore } from '@/stores/dict'

const emit = defineEmits(['update:modelValue', 'saved'])

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  contract: { type: Object, default: null },
})

const formRef = ref()
const submitting = ref(false)
const clientLoading = ref(false)
const clientOptions = ref([])
const caseLoading = ref(false)
const caseOptions = ref([])

const statusMeta = {
  draft: { label: '草稿' },
  active: { label: '生效中' },
  expired: { label: '已到期' },
  terminated: { label: '已终止' },
}

// 合同类型候选走管理端字典（value 存英文标识，历史数据都是这套编码）
const dictStore = useDictStore()
const typeOptions = computed(() => dictStore.options('contract_type'))
dictStore.ensure()

const emptyForm = () => ({
  name: '',
  client_id: null,
  case_id: null,
  contract_type: '',
  amount: 0,
  start_date: '',
  end_date: '',
  status: 'draft',
})

const form = reactive(emptyForm())

const rules = {
  name: [
    { required: true, message: '请输入合同名称', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v && v.trim()) return cb()
        cb(new Error('合同名称不能为空'))
      },
      trigger: 'blur',
    },
  ],
  client_id: [{ required: true, message: '请选择委托客户', trigger: 'change' }],
  amount: [
    { required: true, message: '请输入合同金额', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v == null || v === '') return cb(new Error('请输入合同金额'))
        if (v < 0) return cb(new Error('合同金额不能为负数'))
        if (v > 9999999999.99) return cb(new Error('合同金额不能超过 9999999999.99 元'))
        cb()
      },
      trigger: 'blur',
    },
  ],
  end_date: [
    {
      validator: (_r, v, cb) => {
        if (v && form.start_date && v < form.start_date) {
          return cb(new Error('到期日期不能早于生效日期'))
        }
        cb()
      },
      trigger: 'change',
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

// 选择客户后联动加载该客户的案件
async function onClientChange(clientId) {
  form.case_id = null
  caseOptions.value = []
  if (!clientId) return
  caseLoading.value = true
  try {
    const data = await listCases({ client_id: clientId, page: 1, page_size: 100 })
    caseOptions.value = data.items
  } finally {
    caseLoading.value = false
  }
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  Object.assign(form, emptyForm())
  clientOptions.value = []
  caseOptions.value = []
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = { ...form }
    // 金额/日期/案件按需清理空值
    if (!payload.contract_type) payload.contract_type = null
    if (!payload.start_date) payload.start_date = null
    if (!payload.end_date) payload.end_date = null
    if (!payload.case_id) payload.case_id = null

    if (props.contract) {
      // 编辑：客户不可改，去掉 client_id 空值
      delete payload.client_id
      await updateContract(props.contract.id, payload)
      ElMessage.success('合同已更新')
    } else {
      await createContract(payload)
      ElMessage.success('合同创建成功')
    }
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}

// 打开时：编辑则回填，新建则预加载客户
watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    if (props.contract) {
      Object.assign(form, {
        name: props.contract.name,
        client_id: props.contract.client_id,
        case_id: props.contract.case_id || null,
        contract_type: props.contract.contract_type || '',
        amount: Number(props.contract.amount) || 0,
        start_date: props.contract.start_date || '',
        end_date: props.contract.end_date || '',
        status: props.contract.status,
      })
      // 编辑时回显客户名
      clientOptions.value = [
        { id: props.contract.client_id, name: props.contract.client_name || '当前客户', phone: '' },
      ]
      // 回显该客户的案件列表（含已关联的案件）
      onClientChange(props.contract.client_id).then(() => {
        if (props.contract.case_id) {
          // 若已关联案件不在返回列表里（如已结案被过滤），补一项避免空白
          if (!caseOptions.value.some((c) => c.id === props.contract.case_id)) {
            caseOptions.value.unshift({
              id: props.contract.case_id,
              case_no: '',
              title: props.contract.case_title || '已关联案件',
            })
          }
        }
      })
    } else {
      searchClients('')
    }
  },
)
</script>

<style scoped>
:deep(.el-select) {
  width: 100%;
}
</style>
