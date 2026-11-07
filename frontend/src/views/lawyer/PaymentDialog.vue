<template>
  <el-dialog
    :model-value="modelValue"
    title="登记收款"
    width="600px"
    :close-on-click-modal="false"
    @update:model-value="close"
    @closed="reset"
  >
    <!-- 期次信息 -->
    <div v-if="period" class="period-box">
      <div class="period-head">
        <span class="period-title">第 {{ period.period_no }} 期</span>
        <el-tag v-if="period.due_date" type="info" effect="plain" size="small">
          应收日期 {{ formatDate(period.due_date) }}
        </el-tag>
      </div>
      <div class="amount-row">
        <div class="amount-item">
          <div class="amount-label">应收</div>
          <div class="amount-value">¥{{ money(period.due_amount) }}</div>
        </div>
        <div class="amount-item">
          <div class="amount-label">已收</div>
          <div class="amount-value paid">¥{{ money(period.paid_amount) }}</div>
        </div>
        <div class="amount-item">
          <div class="amount-label">剩余待收</div>
          <div class="amount-value unpaid">¥{{ money(remaining) }}</div>
        </div>
      </div>
    </div>

    <el-form ref="formRef" :model="form" :rules="rules" label-width="90px" class="pay-form">
      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="本次收款" prop="amount">
            <el-input-number
              v-model="form.amount"
              :min="0.01"
              :max="9999999999.99"
              :precision="2"
              :step="1000"
              :controls="false"
              placeholder="0.00"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="收款方式" prop="pay_method">
            <el-select v-model="form.pay_method" placeholder="选择收款方式" clearable style="width: 100%">
              <el-option v-for="m in PAY_METHODS" :key="m" :label="m" :value="m" />
            </el-select>
          </el-form-item>
        </el-col>
      </el-row>

      <el-row :gutter="16">
        <el-col :span="12">
          <el-form-item label="收款时间" prop="paid_at">
            <el-date-picker
              v-model="form.paid_at"
              type="datetime"
              value-format="YYYY-MM-DDTHH:mm:ss"
              placeholder="缺省为当前时间"
              style="width: 100%"
            />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="收据号" prop="receipt_no">
            <el-input v-model="form.receipt_no" placeholder="可选，如 SJ20260101" maxlength="64" />
          </el-form-item>
        </el-col>
      </el-row>

      <el-divider content-position="left">
        <span class="divider-text">发票信息（可选）</span>
      </el-divider>

      <el-form-item label="发票状态" prop="invoice_status">
        <el-radio-group v-model="form.invoice_status">
          <el-radio-button v-for="(m, k) in INVOICE_STATUS_META" :key="k" :value="k">
            {{ m.label }}
          </el-radio-button>
        </el-radio-group>
      </el-form-item>

      <el-row v-if="form.invoice_status !== 'none'" :gutter="16">
        <el-col :span="12">
          <el-form-item label="发票号" prop="invoice_no">
            <el-input v-model="form.invoice_no" placeholder="已开票时必填" maxlength="64" />
          </el-form-item>
        </el-col>
        <el-col :span="12">
          <el-form-item label="开票抬头" prop="invoice_title">
            <el-input v-model="form.invoice_title" placeholder="可选" maxlength="255" />
          </el-form-item>
        </el-col>
      </el-row>
    </el-form>

    <template #footer>
      <el-button @click="close">取消</el-button>
      <el-button type="primary" :loading="submitting" @click="submit">确认收款</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { registerPayment } from '@/api/billing'
import {
  INVOICE_STATUS_META,
  PAY_METHODS,
  PERIOD_STATUS_META,
  formatDate,
  money,
  num,
} from '@/utils/billing'

const emit = defineEmits(['update:modelValue', 'saved'])

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  // 期次：id / period_no / due_amount / paid_amount / due_date / unpaid_amount
  period: { type: Object, default: null },
})

const formRef = ref()
const submitting = ref(false)

// 剩余待收：优先用后端给出的 unpaid_amount，避免前端浮点误差
const remaining = computed(() => {
  if (!props.period) return 0
  if (props.period.unpaid_amount !== undefined && props.period.unpaid_amount !== null) {
    return Math.max(0, num(props.period.unpaid_amount))
  }
  return Math.max(0, num(props.period.due_amount) - num(props.period.paid_amount))
})

function nowStr() {
  const d = new Date()
  const pad = (n) => String(n).padStart(2, '0')
  return (
    `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}` +
    `T${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`
  )
}

const emptyForm = () => ({
  amount: null,
  pay_method: '银行转账',
  paid_at: nowStr(),
  receipt_no: '',
  invoice_status: 'none',
  invoice_no: '',
  invoice_title: '',
})

const form = reactive(emptyForm())

const rules = {
  amount: [
    {
      validator: (_r, v, cb) => {
        if (v == null || v === '') return cb(new Error('请输入本次收款金额'))
        const n = Number(v)
        if (!Number.isFinite(n)) return cb(new Error('请输入正确的金额'))
        if (n <= 0) return cb(new Error('收款金额必须大于 0'))
        if (n > 9999999999.99) return cb(new Error('收款金额不能超过 9999999999.99 元'))
        if (n - remaining.value > 0.005) {
          return cb(new Error(`不能超过本期剩余待收 ¥${money(remaining.value)}`))
        }
        cb()
      },
      trigger: 'blur',
    },
  ],
  invoice_no: [
    {
      validator: (_r, v, cb) => {
        if (form.invoice_status === 'issued' && !(v || '').trim()) {
          return cb(new Error('发票状态为「已开票」时必须填写发票号'))
        }
        cb()
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
  Object.assign(form, emptyForm())
}

async function submit() {
  if (!props.period) return
  await formRef.value.validate()
  submitting.value = true
  try {
    const payload = {
      amount: form.amount,
      pay_method: form.pay_method || null,
      paid_at: form.paid_at || null,
      receipt_no: (form.receipt_no || '').trim() || null,
      invoice_status: form.invoice_status,
      invoice_no: form.invoice_status === 'none' ? null : (form.invoice_no || '').trim() || null,
      invoice_title:
        form.invoice_status === 'none' ? null : (form.invoice_title || '').trim() || null,
    }
    const result = await registerPayment(props.period.id, payload)
    const status = PERIOD_STATUS_META[result.period.status]?.label || '已更新'
    ElMessage.success(
      `收款登记成功，本期已收 ¥${money(result.period.paid_amount)}（${status}）`,
    )
    emit('saved', result)
    close()
  } finally {
    submitting.value = false
  }
}

// 打开时：默认金额填入本期剩余待收
watch(
  () => props.modelValue,
  (v) => {
    if (!v) return
    Object.assign(form, emptyForm())
    form.amount = remaining.value > 0 ? Number(remaining.value.toFixed(2)) : null
  },
)
</script>

<style scoped>
.period-box {
  background: var(--brand-bg);
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 14px 16px;
  margin-bottom: 18px;
}

.period-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 12px;
}

.period-title {
  font-weight: 600;
  color: var(--brand-ink);
}

.amount-row {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 12px;
}

.amount-label {
  font-size: 12px;
  color: var(--brand-muted);
  margin-bottom: 4px;
}

.amount-value {
  font-size: 17px;
  font-weight: 600;
  color: var(--brand-ink);
}

.amount-value.paid {
  color: var(--brand-gold-deep);
}

.amount-value.unpaid {
  color: var(--el-color-danger);
}

.pay-form {
  margin-top: 4px;
}

.divider-text {
  font-size: 13px;
  color: var(--brand-muted);
}
</style>
