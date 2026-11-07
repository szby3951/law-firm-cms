<template>
  <el-dialog
    :model-value="modelValue"
    :title="isEdit ? '编辑日程' : '新建日程'"
    width="620px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="92px" label-position="right">
      <el-form-item label="日程标题" prop="title">
        <el-input
          v-model="form.title"
          placeholder="如：张三诉李四合同纠纷案 第一次开庭"
          maxlength="255"
          show-word-limit
        />
      </el-form-item>

      <el-form-item label="日程类型" prop="schedule_type">
        <el-radio-group v-model="form.schedule_type">
          <el-radio-button v-for="t in SCHEDULE_TYPE_OPTIONS" :key="t.value" :value="t.value">
            {{ t.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="日程时间" prop="event_date">
        <el-date-picker
          v-model="form.event_date"
          type="datetime"
          placeholder="选择日期与时间"
          value-format="YYYY-MM-DDTHH:mm:ss"
          format="YYYY-MM-DD HH:mm"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="提醒时间" prop="remind_at">
        <div class="remind-wrap">
          <el-date-picker
            v-model="form.remind_at"
            type="datetime"
            placeholder="留空则由系统提前 3 天自动提醒"
            value-format="YYYY-MM-DDTHH:mm:ss"
            format="YYYY-MM-DD HH:mm"
            clearable
            style="width: 100%"
          />
          <div class="field-hint">留空时定时任务会在日程前 3 天生成提醒；填写则以该时间为准。</div>
        </div>
      </el-form-item>

      <el-form-item label="关联案件" prop="case_id">
        <el-select
          v-model="form.case_id"
          placeholder="选择关联案件（选填，选定后自动带出委托客户）"
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

      <el-form-item v-if="isAdmin" label="承办律师" prop="user_id">
        <el-select
          v-model="form.user_id"
          placeholder="缺省为本人"
          filterable
          clearable
          style="width: 100%"
        >
          <el-option
            v-for="l in lawyerOptions"
            :key="l.lawyer_id"
            :label="l.lawyer_name"
            :value="l.lawyer_id"
          />
        </el-select>
      </el-form-item>

      <el-form-item v-if="isEdit" label="日程状态" prop="status">
        <el-radio-group v-model="form.status">
          <el-radio value="pending">待办</el-radio>
          <el-radio value="done">已完成</el-radio>
          <el-radio value="cancelled">已取消</el-radio>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="备注" prop="remark">
        <el-input
          v-model="form.remark"
          type="textarea"
          :rows="3"
          placeholder="地点、需携带材料等（选填）"
          maxlength="500"
          show-word-limit
        />
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">
        {{ isEdit ? '保存修改' : '创建日程' }}
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { createSchedule, updateSchedule } from '@/api/schedule'
import { listCases, listLawyers } from '@/api/cases'
import { SCHEDULE_TYPE_OPTIONS, dateKey } from '@/utils/schedule'
import { useUserStore } from '@/stores/user'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 待编辑的日程（为空则为新建）
  schedule: { type: Object, default: null },
  // 新建时的默认日期：YYYY-MM-DD
  defaultDate: { type: String, default: '' },
})

const emit = defineEmits(['update:modelValue', 'saved'])

const userStore = useUserStore()
const isAdmin = computed(() => userStore.role === 'admin')
const isEdit = computed(() => !!props.schedule?.id)

const formRef = ref()
const submitting = ref(false)
const caseLoading = ref(false)
const caseOptions = ref([])
const lawyerOptions = ref([])

const emptyForm = () => ({
  title: '',
  schedule_type: 'hearing',
  event_date: '',
  remind_at: '',
  case_id: null,
  user_id: null,
  status: 'pending',
  remark: '',
})

const form = reactive(emptyForm())

const rules = {
  title: [
    { required: true, message: '请输入日程标题', trigger: 'blur' },
    {
      validator: (_r, v, cb) => {
        if (v && v.trim()) return cb()
        cb(new Error('日程标题不能为空'))
      },
      trigger: 'blur',
    },
    { max: 255, message: '日程标题不能超过 255 个字符', trigger: 'blur' },
  ],
  schedule_type: [{ required: true, message: '请选择日程类型', trigger: 'change' }],
  event_date: [{ required: true, message: '请选择日程时间', trigger: 'change' }],
  remind_at: [
    {
      validator: (_r, v, cb) => {
        if (!v) return cb()
        if (form.event_date && v > form.event_date) {
          return cb(new Error('提醒时间不能晚于日程时间'))
        }
        cb()
      },
      trigger: 'change',
    },
  ],
  remark: [{ max: 500, message: '备注不能超过 500 个字符', trigger: 'blur' }],
}

// 默认时间：默认日期的 09:00，或下一个整点
function defaultEventDate() {
  if (props.defaultDate) return `${props.defaultDate}T09:00:00`
  const now = new Date()
  const next = new Date(now.getTime() + 60 * 60 * 1000)
  next.setMinutes(0, 0, 0)
  const pad = (n) => String(n).padStart(2, '0')
  return `${dateKey(next)}T${pad(next.getHours())}:00:00`
}

function fillFrom(row) {
  form.title = row.title || ''
  form.schedule_type = row.schedule_type || 'hearing'
  form.event_date = String(row.event_date || '').slice(0, 19)
  form.remind_at = row.remind_at ? String(row.remind_at).slice(0, 19) : ''
  form.case_id = row.case_id ?? null
  form.user_id = row.user_id ?? null
  form.status = row.status || 'pending'
  form.remark = row.remark || ''
}

async function loadCases() {
  caseLoading.value = true
  try {
    const data = await listCases({ page: 1, page_size: 100 })
    caseOptions.value = data.items || []
  } catch {
    caseOptions.value = []
  } finally {
    caseLoading.value = false
  }
}

async function loadLawyers() {
  try {
    lawyerOptions.value = await listLawyers()
  } catch {
    lawyerOptions.value = []
  }
}

watch(
  () => props.modelValue,
  (visible) => {
    if (!visible) return
    formRef.value?.clearValidate()
    Object.assign(form, emptyForm())
    if (props.schedule) fillFrom(props.schedule)
    else form.event_date = defaultEventDate()
    loadCases()
    if (isAdmin.value) loadLawyers()
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

  const payload = {
    title: form.title.trim(),
    schedule_type: form.schedule_type,
    event_date: form.event_date,
    remind_at: form.remind_at || null,
    case_id: form.case_id || null,
    // 关联案件时由后端按案件带出委托客户；未关联案件则保留原客户
    client_id: form.case_id ? null : (props.schedule?.client_id ?? null),
    user_id: form.user_id || null,
    status: form.status || 'pending',
    remark: form.remark?.trim() || null,
  }

  submitting.value = true
  try {
    if (isEdit.value) {
      await updateSchedule(props.schedule.id, payload)
      ElMessage.success('日程已更新')
    } else {
      await createSchedule(payload)
      ElMessage.success('日程创建成功')
    }
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.remind-wrap {
  width: 100%;
}

.field-hint {
  font-size: 12px;
  color: var(--brand-muted);
  line-height: 1.6;
  margin-top: 4px;
}
</style>
