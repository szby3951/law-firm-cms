<template>
  <el-dialog
    :model-value="modelValue"
    title="添加跟进记录"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-form-item label="跟进方式" prop="method">
        <el-radio-group v-model="form.method">
          <el-radio-button value="phone">电话</el-radio-button>
          <el-radio-button value="wechat">微信</el-radio-button>
          <el-radio-button value="visit">面访</el-radio-button>
          <el-radio-button value="email">邮件</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="跟进内容" prop="content">
        <el-input
          v-model="form.content"
          type="textarea"
          :rows="4"
          placeholder="记录本次沟通要点、客户诉求与反馈"
          maxlength="2000"
          show-word-limit
        />
      </el-form-item>

      <el-form-item label="下次跟进" prop="next_follow_date">
        <el-date-picker
          v-model="form.next_follow_date"
          type="date"
          placeholder="选择日期（选填）"
          value-format="YYYY-MM-DD"
          :clearable="true"
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
import { addFollow } from '@/api/clients'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  clientId: { type: Number, required: true },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const formRef = ref()
const submitting = ref(false)

const form = reactive({
  method: 'phone',
  content: '',
  next_follow_date: '',
})

const rules = {
  content: [
    { required: true, message: '请输入跟进内容', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v && v.trim()) return cb()
        cb(new Error('跟进内容不能为空'))
      },
      trigger: 'blur',
    },
  ],
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  form.method = 'phone'
  form.content = ''
  form.next_follow_date = ''
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = {
      method: form.method,
      content: form.content,
      next_follow_date: form.next_follow_date || null,
    }
    await addFollow(props.clientId, payload)
    ElMessage.success('跟进记录已添加')
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
