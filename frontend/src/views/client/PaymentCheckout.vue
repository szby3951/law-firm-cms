<template>
  <el-dialog
    v-model="visible"
    width="620px"
    class="checkout-dialog"
    :show-close="step !== 'paying'"
    :close-on-click-modal="step === 'confirm'"
    :close-on-press-escape="step !== 'paying'"
    @closed="reset"
  >
    <template #header>
      <div class="checkout-head">
        <span class="checkout-title">在线缴费</span>
        <span class="sandbox-pill">沙箱环境</span>
      </div>
    </template>

    <!-- 1. 确认金额与支付方式 -->
    <template v-if="step === 'confirm'">
      <div v-if="bill" class="bill-card">
        <div class="bill-title">{{ bill.case_title || `案件 #${bill.case_id}` }}</div>
        <div class="bill-sub">
          {{ bill.case_no || '—' }} · 第 {{ bill.period_no }} 期
        </div>
        <div class="bill-amount-row">
          <div>
            <div class="bill-label">待缴金额</div>
            <div class="bill-amount">¥{{ money(bill.unpaid_amount) }}</div>
          </div>
          <div class="bill-meta">
            <div>应收 ¥{{ money(bill.due_amount) }}</div>
            <div>已缴 ¥{{ money(bill.paid_amount) }}</div>
            <div>应收日期 {{ formatDate(bill.due_date) }}</div>
          </div>
        </div>
      </div>

      <div class="field">
        <div class="field-label">
          <span>缴费金额</span>
          <el-button link type="primary" size="small" @click="amount = unpaid">
            按全额缴纳
          </el-button>
        </div>
        <el-input-number
          v-model="amount"
          :min="0.01"
          :max="unpaid || undefined"
          :precision="2"
          :step="1000"
          :controls="false"
          size="large"
          class="amount-input"
        />
        <div class="field-tip">支持部分缴费，剩余待缴以账单页为准</div>
      </div>

      <div class="field">
        <div class="field-label"><span>支付方式</span></div>
        <div class="channel-list">
          <div
            v-for="c in CHANNELS"
            :key="c.value"
            class="channel"
            :class="{ active: channel === c.value }"
            @click="channel = c.value"
          >
            <el-icon :size="22" :style="{ color: c.color }">
              <component :is="c.icon" />
            </el-icon>
            <div class="channel-text">
              <div class="channel-name">{{ c.label }}</div>
              <div class="channel-desc">{{ c.desc }}</div>
            </div>
            <el-icon v-if="channel === c.value" class="channel-check"><Check /></el-icon>
          </div>
        </div>
      </div>

      <el-collapse v-model="guideOpen" class="guide">
        <el-collapse-item name="offline">
          <template #title>
            <span class="guide-title">改为线下转账（对公账户）</span>
          </template>
          <div class="guide-body">
            <div class="guide-line">
              1. 向承办律师索取本所对公账户与开票信息，或到律所财务处缴纳。
              <div class="lawyer-line">
                承办律师：
                <span v-if="lawyerLoading">加载中…</span>
                <span v-else-if="lawyerText">{{ lawyerText }}</span>
                <span v-else>请联系律所前台或承办律师</span>
              </div>
            </div>
            <div class="guide-line">
              2. 转账备注：
              <span class="remark">{{ payRemark }}</span>
              <el-button link type="primary" size="small" @click="copyRemark">复制</el-button>
            </div>
            <div class="guide-line">
              3. 保留凭证并告知承办律师，律师登记后本页状态自动更新。
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>

      <div class="sandbox-note">
        <el-icon><InfoFilled /></el-icon>
        <span>
          沙箱模拟支付：不会产生真实扣款；支付成功后立即写入收费台账，律师端与管理员端同步可见。
        </span>
      </div>
    </template>

    <!-- 2. 支付中 -->
    <div v-else-if="step === 'paying'" class="paying">
      <el-icon class="is-loading paying-icon" :size="38"><Loading /></el-icon>
      <div class="paying-title">正在与支付网关通信…</div>
      <div class="paying-desc">请勿关闭窗口</div>
    </div>

    <!-- 3. 支付成功 -->
    <div v-else-if="step === 'success'" class="result">
      <el-icon class="result-icon success" :size="52"><CircleCheckFilled /></el-icon>
      <div class="result-title">支付成功</div>
      <div class="result-amount">¥{{ money(payment?.amount || order?.amount) }}</div>
      <div class="result-rows">
        <div class="result-row">
          <span>支付方式</span><b>{{ order?.channel_label }}</b>
        </div>
        <div class="result-row">
          <span>订单号</span><b class="mono">{{ order?.order_no }}</b>
        </div>
        <div class="result-row">
          <span>交易号</span><b class="mono">{{ order?.transaction_no || '—' }}</b>
        </div>
        <div class="result-row">
          <span>支付时间</span><b>{{ formatTime(order?.paid_at) }}</b>
        </div>
      </div>
      <div class="result-tip">收款已登记，律师端收费台账与营收统计已同步更新。</div>
    </div>

    <!-- 4. 支付失败 -->
    <div v-else class="result">
      <el-icon class="result-icon failed" :size="52"><CircleCloseFilled /></el-icon>
      <div class="result-title">支付未完成</div>
      <div class="result-reason">{{ errorMsg || '支付失败，请重试' }}</div>
      <div class="result-tip">本次未产生任何收款记录，账单状态不会变化。</div>
    </div>

    <template #footer>
      <div class="checkout-footer">
        <template v-if="step === 'confirm'">
          <el-button text class="fail-link" @click="submit('failed')">演示支付失败</el-button>
          <div>
            <el-button @click="visible = false">取消</el-button>
            <el-button type="primary" :loading="submitting" @click="submit('success')">
              确认支付 ¥{{ money(amount) }}
            </el-button>
          </div>
        </template>
        <template v-else-if="step === 'paying'">
          <span />
          <el-button disabled>支付处理中</el-button>
        </template>
        <template v-else-if="step === 'success'">
          <span />
          <el-button type="primary" @click="visible = false">完成</el-button>
        </template>
        <template v-else>
          <span />
          <div>
            <el-button @click="step = 'confirm'">返回修改</el-button>
            <el-button type="primary" @click="submit('success')">重新支付</el-button>
          </div>
        </template>
      </div>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  ChatDotRound,
  Check,
  CircleCheckFilled,
  CircleCloseFilled,
  CreditCard,
  InfoFilled,
  Loading,
  Money,
} from '@element-plus/icons-vue'
import { createPaymentOrder, sandboxPay } from '@/api/billing'
import { getMyCase } from '@/api/cases'
import { formatDate, formatTime, money, num } from '@/utils/billing'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  bill: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'paid'])

const CHANNELS = [
  {
    value: 'wechat',
    label: '微信支付',
    icon: ChatDotRound,
    color: '#07c160',
    desc: '沙箱模拟扫码',
  },
  { value: 'alipay', label: '支付宝', icon: Money, color: '#1677ff', desc: '沙箱模拟扫码' },
  {
    value: 'bank',
    label: '银行卡',
    icon: CreditCard,
    color: '#1d2b47',
    desc: '沙箱模拟快捷支付',
  },
]

const visible = computed({
  get: () => props.modelValue,
  set: (v) => emit('update:modelValue', v),
})

const step = ref('confirm')
const channel = ref('wechat')
const amount = ref(0)
const order = ref(null)
const payment = ref(null)
const errorMsg = ref('')
const submitting = ref(false)
const guideOpen = ref([])

const unpaid = computed(() => num(props.bill?.unpaid_amount))

watch(
  () => props.bill,
  (bill) => {
    if (bill) amount.value = num(bill.unpaid_amount)
  },
  { immediate: true },
)

watch(
  () => props.modelValue,
  (open) => {
    if (open) reset()
  },
)

// 线下转账指引：承办律师按案件缓存，避免每次打开都请求
const lawyerMap = ref({})
const lawyerLoading = ref(false)

const DUTY_LABEL = { lead: '主办', assist: '协办' }
const lawyerText = computed(() =>
  (lawyerMap.value[props.bill?.case_id] || [])
    .map((l) => `${l.lawyer_name || '律师'}（${DUTY_LABEL[l.duty] || l.duty}）`)
    .join('、'),
)

const payRemark = computed(() => {
  if (!props.bill) return ''
  const no = props.bill.case_no || `案件${props.bill.case_id}`
  return `${no} 第${props.bill.period_no}期律师费`
})

async function loadLawyers() {
  const caseId = props.bill?.case_id
  if (!caseId || lawyerMap.value[caseId] || lawyerLoading.value) return
  lawyerLoading.value = true
  try {
    const detail = await getMyCase(caseId)
    lawyerMap.value[caseId] = detail.lawyers || []
  } catch {
    lawyerMap.value[caseId] = []
  } finally {
    lawyerLoading.value = false
  }
}

watch(guideOpen, (v) => {
  if (v.includes('offline')) loadLawyers()
})

async function copyRemark() {
  const text = payRemark.value
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('转账备注已复制')
  } catch {
    ElMessage.info(`请手动复制：${text}`)
  }
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

async function submit(result) {
  if (!props.bill) return
  if (result === 'success') {
    const n = num(amount.value)
    if (n <= 0) return ElMessage.warning('请输入缴费金额')
    if (n - unpaid.value > 0.001) return ElMessage.warning('缴费金额不能超过待缴金额')
  }

  submitting.value = true
  const originStep = step.value
  step.value = 'paying'
  errorMsg.value = ''

  try {
    // 同一金额/渠道复用未支付订单，避免重复下单
    let current = order.value
    const needNew =
      !current ||
      num(current.amount) !== num(amount.value) ||
      current.channel !== channel.value ||
      current.status !== 'pending'
    if (needNew) {
      current = await createPaymentOrder(props.bill.period_id, {
        amount: num(amount.value),
        channel: channel.value,
      })
      order.value = current
    }

    await sleep(1100) // 模拟网关往返，让状态切换可感知
    const res = await sandboxPay(current.order_no, { result })
    order.value = res.order

    if (result === 'success') {
      payment.value = res.payment
      step.value = 'success'
      emit('paid')
    } else {
      errorMsg.value = res.order?.fail_reason || '支付未完成'
      step.value = 'failed'
      order.value = null
    }
  } catch (e) {
    errorMsg.value =
      e?.response?.data?.detail || e?.message || '支付请求失败，请稍后重试'
    step.value = 'failed'
    order.value = null
  } finally {
    submitting.value = false
    if (step.value === 'paying') step.value = originStep
  }
}

function reset() {
  step.value = 'confirm'
  order.value = null
  payment.value = null
  errorMsg.value = ''
  guideOpen.value = []
  if (props.bill) amount.value = num(props.bill.unpaid_amount)
}
</script>

<style scoped>
.checkout-head {
  display: flex;
  align-items: center;
  gap: 8px;
}

.checkout-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-ink);
}

.sandbox-pill {
  font-size: 11px;
  color: #a5813d;
  background: #faf3e7;
  border: 1px solid #efe0c4;
  border-radius: 10px;
  padding: 1px 8px;
}

.bill-card {
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 100%);
  border-radius: 12px;
  padding: 18px 20px;
  color: #fff;
  margin-bottom: 20px;
}

.bill-title {
  font-size: 15px;
  font-weight: 600;
}

.bill-sub {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
  margin-top: 5px;
}

.bill-amount-row {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  margin-top: 14px;
}

.bill-label {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.bill-amount {
  font-size: 28px;
  font-weight: 600;
  color: var(--brand-gold-light);
  letter-spacing: 0.5px;
  margin-top: 4px;
}

.bill-meta {
  text-align: right;
  font-size: 12px;
  line-height: 1.9;
  color: rgba(255, 255, 255, 0.55);
}

.field {
  margin-bottom: 18px;
}

.field-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-bottom: 8px;
}

.amount-input {
  width: 100%;
}

.amount-input :deep(.el-input__inner) {
  font-size: 18px;
  font-weight: 600;
  color: var(--brand-gold-deep);
  text-align: left;
}

.field-tip {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 6px;
}

.channel-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.channel {
  display: flex;
  align-items: center;
  gap: 12px;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 11px 14px;
  cursor: pointer;
  transition: all 0.18s;
}

.channel:hover {
  border-color: var(--brand-gold);
}

.channel.active {
  border-color: var(--brand-gold);
  background: #fdfaf3;
  box-shadow: 0 0 0 1px var(--brand-gold) inset;
}

.channel-text {
  flex: 1;
}

.channel-name {
  font-size: 14px;
  color: var(--brand-text);
  font-weight: 500;
}

.channel-desc {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.channel-check {
  color: var(--brand-gold-deep);
}

.guide {
  border-top: none;
  border-bottom: none;
  margin-bottom: 8px;
}

.guide-title {
  font-size: 13px;
  color: var(--brand-muted);
}

.guide-body {
  font-size: 13px;
  color: var(--brand-muted);
  line-height: 1.9;
  padding-left: 2px;
}

.guide-line {
  margin-bottom: 6px;
}

.lawyer-line {
  color: var(--brand-text);
}

.remark {
  color: var(--brand-text);
  background: var(--brand-bg);
  border: 1px solid var(--brand-line);
  border-radius: 4px;
  padding: 1px 6px;
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.sandbox-note {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: 12px;
  line-height: 1.7;
  color: #a5813d;
  background: #faf3e7;
  border-radius: 8px;
  padding: 10px 12px;
}

.paying {
  padding: 42px 0 50px;
  text-align: center;
}

.paying-icon {
  color: var(--brand-gold);
}

.paying-title {
  margin-top: 14px;
  font-size: 15px;
  color: var(--brand-ink);
  font-weight: 600;
}

.paying-desc {
  margin-top: 6px;
  font-size: 12px;
  color: var(--brand-muted);
}

.result {
  padding: 26px 0 8px;
  text-align: center;
}

.result-icon.success {
  color: #1d9e75;
}

.result-icon.failed {
  color: var(--el-color-danger);
}

.result-title {
  margin-top: 12px;
  font-size: 17px;
  font-weight: 600;
  color: var(--brand-ink);
}

.result-amount {
  margin-top: 6px;
  font-size: 30px;
  font-weight: 600;
  color: var(--brand-gold-deep);
}

.result-rows {
  margin: 18px auto 0;
  max-width: 380px;
  border-top: 1px dashed var(--brand-line);
  padding-top: 12px;
}

.result-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--brand-muted);
  line-height: 2;
}

.result-row b {
  color: var(--brand-text);
  font-weight: 500;
}

.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.result-reason {
  margin-top: 10px;
  font-size: 13px;
  color: var(--el-color-danger);
  background: #faeef0;
  border-radius: 8px;
  padding: 10px 12px;
  line-height: 1.7;
}

.result-tip {
  margin-top: 14px;
  font-size: 12px;
  color: var(--brand-muted);
}

.checkout-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.fail-link {
  color: var(--brand-muted);
  font-size: 12px;
}
</style>
