<template>
  <el-dialog
    :model-value="modelValue"
    title="登记案件事件"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-form-item label="事件类型" prop="event_type">
        <el-select v-model="form.event_type" placeholder="选择事件类型" style="width: 100%">
          <el-option v-for="(m, k) in eventMeta" :key="k" :label="m.label" :value="k" />
        </el-select>
      </el-form-item>

      <el-form-item label="节点时间" prop="event_date">
        <el-date-picker
          v-model="form.event_date"
          type="datetime"
          placeholder="选择节点时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="事件说明" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="3"
          placeholder="记录本次节点详情（选填）"
          maxlength="500"
          show-word-limit
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">提交</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { addCaseEvent } from '@/api/cases'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  caseId: { type: Number, required: true },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const formRef = ref()
const submitting = ref(false)

const eventMeta = {
  filing: { label: '立案' },
  accept: { label: '受理' },
  hearing: { label: '开庭' },
  evidence: { label: '举证' },
  judgment: { label: '判决' },
  other: { label: '其他' },
}

const form = reactive({
  event_type: 'other',
  event_date: '',
  description: '',
})

const rules = {
  event_type: [{ required: true, message: '请选择事件类型', trigger: 'change' }],
  event_date: [{ required: true, message: '请选择节点时间', trigger: 'change' }],
  description: [{ max: 500, message: '事件说明不能超过 500 个字符', trigger: 'blur' }],
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  form.event_type = 'other'
  form.event_date = ''
  form.description = ''
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    await addCaseEvent(props.caseId, { ...form, description: form.description || null })
    ElMessage.success('事件已登记')
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
:deep(.el-date-editor) {
  width: 100%;
}
</style>
