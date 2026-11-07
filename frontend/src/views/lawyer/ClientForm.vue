<template>
  <el-dialog
    :model-value="modelValue"
    :title="client ? '编辑客户' : '新增客户'"
    width="640px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form
      ref="formRef"
      :model="form"
      :rules="rules"
      label-width="92px"
      label-position="right"
    >
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="姓名" prop="name">
            <el-input v-model="form.name" placeholder="客户姓名 / 机构名称" maxlength="64" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="客户类型" prop="client_type">
            <el-radio-group v-model="form.client_type">
              <el-radio-button value="personal">个人</el-radio-button>
              <el-radio-button value="company">机构</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="联系电话" prop="phone">
            <el-input v-model="form.phone" placeholder="手机或座机" maxlength="20" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="证件号" prop="id_no">
            <el-input v-model="form.id_no" placeholder="身份证 / 统一社会信用代码" maxlength="64" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="性别" prop="gender">
            <el-select v-model="form.gender" placeholder="请选择" clearable>
              <el-option label="男" value="男" />
              <el-option label="女" value="女" />
            </el-select>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="来源渠道" prop="source_channel">
            <el-select
              v-model="form.source_channel"
              placeholder="请选择"
              clearable
              filterable
              allow-create
              default-first-option
            >
              <el-option
                v-for="o in sourceOptions"
                :key="o.value"
                :label="o.label"
                :value="o.label"
              />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="联系地址" prop="address">
        <el-input v-model="form.address" placeholder="客户常住地址" maxlength="255" />
      </el-form-item>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="客户分级" prop="level">
            <el-radio-group v-model="form.level">
              <el-radio-button value="normal">普通</el-radio-button>
              <el-radio-button value="vip">VIP</el-radio-button>
            </el-radio-group>
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="漏斗状态" prop="status">
            <el-select v-model="form.status" placeholder="请选择">
              <el-option label="潜在" value="potential" />
              <el-option label="成交" value="deal" />
              <el-option label="流失" value="lost" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-form-item label="备注" prop="remark">
        <el-input v-model="form.remark" type="textarea" :rows="3" placeholder="补充说明（选填）" />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">保存</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { createClient, updateClient } from '@/api/clients'
import { useDictStore } from '@/stores/dict'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  client: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const formRef = ref()
const submitting = ref(false)

// 来源渠道读管理端字典，历史数据存的是中文标签，这里也用标签作取值
const dictStore = useDictStore()
const sourceOptions = computed(() => dictStore.options('source_channel'))
dictStore.ensure()

const emptyForm = () => ({
  name: '',
  client_type: 'personal',
  phone: '',
  id_no: '',
  gender: '',
  source_channel: '',
  address: '',
  level: 'normal',
  status: 'potential',
  remark: '',
})

const form = reactive(emptyForm())

const rules = {
  name: [
    { required: true, message: '请输入客户姓名', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v && v.trim()) return cb()
        cb(new Error('客户姓名不能为空'))
      },
      trigger: 'blur',
    },
  ],
  phone: [
    { pattern: /^[\d\-+]{3,20}$/, message: '联系电话格式不正确（仅数字、-、+，3~20 位）', trigger: 'blur' },
  ],
  id_no: [{ max: 64, message: '证件号不能超过 64 位', trigger: 'blur' }],
  address: [{ max: 255, message: '联系地址不能超过 255 个字符', trigger: 'blur' }],
}

// 编辑态回填
function fill() {
  const c = props.client
  if (!c) {
    Object.assign(form, emptyForm())
    return
  }
  Object.assign(form, {
    name: c.name,
    client_type: c.client_type,
    phone: c.phone || '',
    id_no: c.id_no || '',
    gender: c.gender || '',
    source_channel: c.source_channel || '',
    address: c.address || '',
    level: c.level,
    status: c.status,
    remark: c.remark || '',
  })
}

// 弹窗打开时初始化（用 watch 监听 modelValue）
import { watch } from 'vue'
watch(
  () => props.modelValue,
  (v) => {
    if (v) fill()
  },
)

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  Object.assign(form, emptyForm())
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = { ...form }
    if (props.client) {
      await updateClient(props.client.id, payload)
      ElMessage.success('已保存')
    } else {
      await createClient(payload)
      ElMessage.success('已新增')
    }
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
:deep(.el-select) {
  width: 100%;
}
</style>
