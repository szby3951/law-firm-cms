<template>
  <el-dialog
    :model-value="modelValue"
    title="案件分案"
    width="520px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-alert
        v-if="caseTitle"
        :title="caseTitle"
        type="info"
        :closable="false"
        show-icon
        class="tip"
      />

      <el-form-item label="主办律师" prop="lead_lawyer_id">
        <el-select v-model="form.lead_lawyer_id" placeholder="选择主办律师" filterable style="width: 100%">
          <el-option v-for="l in lawyers" :key="l.lawyer_id" :label="l.lawyer_name" :value="l.lawyer_id" />
        </el-select>
      </el-form-item>

      <el-form-item label="协办律师" prop="assist_lawyer_ids">
        <el-select
          v-model="form.assist_lawyer_ids"
          placeholder="选择协办律师（可多选）"
          multiple
          filterable
          style="width: 100%"
        >
          <el-option
            v-for="l in lawyers"
            :key="l.lawyer_id"
            :label="l.lawyer_name"
            :value="l.lawyer_id"
            :disabled="l.lawyer_id === form.lead_lawyer_id"
          />
        </el-select>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认分案</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { assignCase, listLawyers } from '@/api/cases'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  caseId: { type: Number, default: null },
  caseTitle: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const formRef = ref()
const submitting = ref(false)
const lawyers = ref([])

const form = reactive({
  lead_lawyer_id: null,
  assist_lawyer_ids: [],
})

const rules = {
  lead_lawyer_id: [{ required: true, message: '请选择主办律师', trigger: 'change' }],
}

async function loadLawyers() {
  lawyers.value = await listLawyers()
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  form.lead_lawyer_id = null
  form.assist_lawyer_ids = []
}

async function submit() {
  await formRef.value.validate()
  submitting.value = true
  try {
    await assignCase(props.caseId, {
      lead_lawyer_id: form.lead_lawyer_id,
      assist_lawyer_ids: form.assist_lawyer_ids,
    })
    ElMessage.success('分案成功')
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}

watch(
  () => props.modelValue,
  (v) => {
    if (v) loadLawyers()
  },
)
</script>

<style scoped>
.tip {
  margin-bottom: 16px;
}
</style>
