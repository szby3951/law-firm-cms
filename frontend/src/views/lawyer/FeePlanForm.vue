<template>
  <el-dialog
    :model-value="modelValue"
    title="新建收费方案"
    width="720px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <el-form ref="formRef" :model="form" :rules="rules" label-width="96px" label-position="right">
      <el-form-item label="关联案件" prop="case_id">
        <el-select
          v-model="form.case_id"
          placeholder="输入案号或案件标题搜索"
          filterable
          remote
          clearable
          :remote-method="searchCases"
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

      <el-form-item label="收费方式" prop="fee_type">
        <el-radio-group v-model="form.fee_type">
          <el-radio-button v-for="(m, k) in FEE_TYPE_META" :key="k" :value="k">
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-form-item label="收费总额" prop="total_amount">
        <el-input-number
          v-model="form.total_amount"
          :min="0"
          :max="9999999999.99"
          :precision="2"
          :step="10000"
          :controls="false"
          placeholder="0.00"
          style="width: 100%"
        />
      </el-form-item>

      <el-form-item label="收费说明" prop="description">
        <el-input
          v-model="form.description"
          type="textarea"
          :rows="2"
          maxlength="500"
          show-word-limit
          placeholder="可选，如：一审代理费，分两期支付"
        />
      </el-form-item>

      <el-form-item label="收款安排" prop="split">
        <el-radio-group v-model="form.split">
          <el-radio-button value="single">一次性收款</el-radio-button>
          <el-radio-button value="installment">分期收款</el-radio-button>
        </el-radio-group>
      </el-form-item>

      <!-- 分期计划 -->
      <el-form-item v-if="form.split === 'installment'" label="分期计划">
        <div class="period-editor">
          <div v-for="(p, i) in form.periods" :key="i" class="period-row">
            <span class="period-no">第 {{ i + 1 }} 期</span>
            <el-input-number
              v-model="p.due_amount"
              :min="0"
              :max="9999999999.99"
              :precision="2"
              :controls="false"
              placeholder="应收金额"
              class="period-amount"
            />
            <el-date-picker
              v-model="p.due_date"
              type="date"
              value-format="YYYY-MM-DD"
              placeholder="应收日期"
              class="period-date"
            />
            <el-button
              link
              type="danger"
              :disabled="form.periods.length <= 2"
              @click="removePeriod(i)"
            >
              删除
            </el-button>
          </div>

          <div class="period-foot">
            <div class="period-actions">
              <el-button link type="primary" @click="addPeriod">
                <el-icon><Plus /></el-icon>添加一期
              </el-button>
              <el-button link type="primary" @click="splitEvenly">按总额均分</el-button>
            </div>
            <div class="period-sum" :class="{ 'is-bad': diff !== 0 }">
              合计 ¥{{ money(periodSum) }} / 总额 ¥{{ money(form.total_amount) }}
              <span v-if="diff !== 0">（差额 ¥{{ money(Math.abs(diff)) }}）</span>
              <span v-else class="ok">✓ 金额一致</span>
            </div>
          </div>

          <el-alert
            v-if="diff !== 0"
            title="各期应收合计需与收费总额一致，否则无法保存"
            type="warning"
            :closable="false"
            show-icon
            class="sum-alert"
          />
        </div>
      </el-form-item>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">创建方案</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { Plus } from '@element-plus/icons-vue'
import { createFeePlan } from '@/api/billing'
import { listCases } from '@/api/cases'
import { FEE_TYPE_META, money, num } from '@/utils/billing'

const emit = defineEmits(['update:modelValue', 'saved'])

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 可选：从收费列表带入的案件
  caseId: { type: Number, default: null },
})

const formRef = ref()
const submitting = ref(false)
const caseLoading = ref(false)
const caseOptions = ref([])

const emptyForm = () => ({
  case_id: props.caseId || null,
  fee_type: 'fixed',
  total_amount: null,
  description: '',
  split: 'single',
  periods: [newPeriod(1), newPeriod(2)],
})

const form = reactive(emptyForm())

// 各期应收合计与差额
const periodSum = computed(() =>
  form.periods.reduce((acc, p) => acc + num(p.due_amount), 0),
)
const diff = computed(() => {
  if (form.split !== 'installment') return 0
  return Number((periodSum.value - num(form.total_amount)).toFixed(2))
})

const rules = {
  case_id: [{ required: true, message: '请选择关联案件', trigger: 'change' }],
  total_amount: [
    {
      validator: (_r, v, cb) => {
        if (v == null || v === '') return cb(new Error('请输入收费总额'))
        const n = Number(v)
        if (!Number.isFinite(n)) return cb(new Error('请输入正确的金额'))
        if (n <= 0) return cb(new Error('收费总额必须大于 0'))
        if (n > 9999999999.99) return cb(new Error('收费总额不能超过 9999999999.99 元'))
        cb()
      },
      trigger: 'blur',
    },
  ],
}

// 往后推 n 天（默认按 30 天一期给个合理默认值，可手动改）
function plusDays(days) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function newPeriod(index) {
  return { due_amount: null, due_date: plusDays(30 * index) }
}

async function searchCases(keyword) {
  caseLoading.value = true
  try {
    const data = await listCases({ keyword, page: 1, page_size: 100 })
    caseOptions.value = data.items
  } finally {
    caseLoading.value = false
  }
}

function addPeriod() {
  const len = form.periods.length
  const last = form.periods[len - 1]
  // 新增一期默认吃掉剩余差额，方便把总计补齐
  const rest = Math.max(0, Number((num(form.total_amount) - periodSum.value).toFixed(2)))
  form.periods.push({
    due_amount: rest > 0 ? rest : null,
    due_date: last?.due_date ? shiftDate(last.due_date, 30) : plusDays(30 * (len + 1)),
  })
}

function shiftDate(dateStr, days) {
  const d = new Date(`${dateStr}T00:00:00`)
  if (Number.isNaN(d.getTime())) return plusDays(30)
  d.setDate(d.getDate() + days)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

function removePeriod(index) {
  if (form.periods.length <= 2) return
  form.periods.splice(index, 1)
}

// 按总额均分：前 n-1 期取整到分，尾期吸收余数，保证合计等于总额
function splitEvenly() {
  const total = num(form.total_amount)
  if (total <= 0) {
    ElMessage.warning('请先填写收费总额')
    return
  }
  const n = form.periods.length
  const per = Math.floor((total * 100) / n) / 100
  form.periods.forEach((p, i) => {
    p.due_amount = i === n - 1 ? Number((total - per * (n - 1)).toFixed(2)) : per
    if (!p.due_date) p.due_date = plusDays(30 * (i + 1))
  })
}

function close() {
  emit('update:modelValue', false)
}

function reset() {
  formRef.value?.clearValidate()
  Object.assign(form, {
    case_id: props.caseId || null,
    fee_type: 'fixed',
    total_amount: null,
    description: '',
    split: 'single',
    periods: [newPeriod(1), newPeriod(2)],
  })
  caseOptions.value = []
}

async function submit() {
  await formRef.value.validate()
  if (form.split === 'installment') {
    if (form.periods.some((p) => num(p.due_amount) <= 0)) {
      ElMessage.error('每期应收金额必须大于 0')
      return
    }
    if (diff.value !== 0) {
      ElMessage.error('各期应收合计与收费总额不一致，请核对分期金额')
      return
    }
  }

  submitting.value = true
  try {
    const payload = {
      case_id: form.case_id,
      fee_type: form.fee_type,
      total_amount: form.total_amount,
      description: (form.description || '').trim() || null,
      periods:
        form.split === 'installment'
          ? form.periods.map((p, i) => ({
              period_no: i + 1,
              due_amount: p.due_amount,
              due_date: p.due_date || null,
            }))
          : [],
    }
    await createFeePlan(payload)
    ElMessage.success(
      form.split === 'installment'
        ? `收费方案已创建，共生成 ${payload.periods.length} 期`
        : '收费方案已创建（一次性收款）',
    )
    emit('saved')
    close()
  } finally {
    submitting.value = false
  }
}

// 打开时加载案件列表
watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    searchCases('')
  },
)

// 一次性收款时清掉分期差额提示
watch(
  () => form.split,
  (v) => {
    if (v === 'single') formRef.value?.clearValidate('split')
  },
)
</script>

<style scoped>
.period-editor {
  width: 100%;
  border: 1px dashed var(--brand-line);
  border-radius: 10px;
  padding: 12px 14px;
  background: var(--brand-bg);
}

.period-row {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 10px;
}

.period-no {
  width: 56px;
  font-size: 13px;
  color: var(--brand-muted);
  flex-shrink: 0;
}

.period-amount {
  width: 170px;
}

.period-date {
  width: 160px !important;
}

.period-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
  padding-top: 4px;
}

.period-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.period-sum {
  font-size: 13px;
  color: var(--brand-muted);
}

.period-sum .ok {
  color: var(--el-color-success);
  margin-left: 4px;
}

.period-sum.is-bad {
  color: var(--el-color-danger);
}

.sum-alert {
  margin-top: 10px;
}

/* 日期选择器在 flex 容器内需要固定宽度 */
:deep(.period-date .el-input__wrapper) {
  width: 100%;
}
</style>
