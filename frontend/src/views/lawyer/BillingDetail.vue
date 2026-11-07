<template>
  <div class="billing-detail" v-loading="loading">
    <div class="back-bar">
      <el-button link @click="back">
        <el-icon><ArrowLeft /></el-icon>返回收费列表
      </el-button>
    </div>

    <template v-if="detail">
      <!-- 方案信息 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>收费方案</span>
            <el-tag :type="planStatusMeta(detail).type" effect="light" size="small">
              {{ planStatusMeta(detail).label }}
            </el-tag>
          </div>
        </template>

        <div class="plan-head">
          <div class="plan-title">{{ detail.case_title || `案件 #${detail.case_id}` }}</div>
          <div class="plan-sub">
            <span>{{ detail.case_no || '—' }}</span>
            <el-divider direction="vertical" />
            <span>委托客户：{{ detail.client_name || '—' }}</span>
            <el-divider direction="vertical" />
            <el-link type="primary" :underline="false" @click="goCase">查看案件</el-link>
          </div>
        </div>

        <el-descriptions :column="3" border class="desc">
          <el-descriptions-item label="收费方式">
            <el-tag :type="FEE_TYPE_META[detail.fee_type]?.type || 'info'" effect="plain" size="small">
              {{ FEE_TYPE_META[detail.fee_type]?.label || detail.fee_type }}
            </el-tag>
          </el-descriptions-item>
          <el-descriptions-item label="收费总额">
            <span class="amount">¥{{ money(detail.total_amount) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="期次数">{{ detail.periods?.length || 0 }} 期</el-descriptions-item>
          <el-descriptions-item label="已收金额">
            <span class="amount">¥{{ money(detail.paid_total) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="未收金额">
            <span class="unpaid">¥{{ money(unpaidTotal) }}</span>
          </el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(detail.created_at) }}</el-descriptions-item>
        </el-descriptions>

        <div class="progress-box">
          <div class="progress-label">
            <span>回款进度</span>
            <span class="progress-num">
              已收 ¥{{ money(detail.paid_total) }} / 应收 ¥{{ money(detail.due_total) }}
              （{{ progressPercent(detail.due_total, detail.paid_total) }}%）
            </span>
          </div>
          <el-progress
            :percentage="progressPercent(detail.due_total, detail.paid_total)"
            :stroke-width="10"
            :color="progressColor"
          />
        </div>

        <div v-if="detail.description" class="description-box">
          <span class="desc-label">收费说明</span>
          <span class="desc-text">{{ detail.description }}</span>
        </div>

        <el-alert
          v-if="detail.pending_order_count > 0"
          type="warning"
          :closable="false"
          show-icon
          class="pending-alert"
        >
          <template #title>
            客户有 {{ detail.pending_order_count }} 笔在线支付正在进行中（合计 ¥{{
              money(detail.pending_order_amount)
            }}），请勿重复登记收款，避免与在线支付冲突
          </template>
        </el-alert>
      </el-card>

      <!-- 分期计划 -->
      <el-card shadow="never" class="section">
        <template #header>
          <div class="card-head">
            <span>分期计划</span>
            <div class="head-actions">
              <el-button size="small" plain @click="openOrders">
                <el-icon><Tickets /></el-icon>支付订单
              </el-button>
              <el-button type="primary" size="small" plain @click="openAddPeriod">
                <el-icon><Plus /></el-icon>追加期次
              </el-button>
            </div>
          </div>
        </template>

        <el-table
          :data="detail.periods"
          row-key="id"
          style="width: 100%"
          @expand-change="onExpand"
        >
          <el-table-column type="expand">
            <template #default="{ row }">
              <div class="expand-box" v-loading="!!paymentsLoading[row.id]">
                <div class="expand-head">
                  <span>第 {{ row.period_no }} 期收款流水</span>
                  <span class="sub">共 {{ (payments[row.id] || []).length }} 笔</span>
                </div>

                <el-table
                  v-if="(payments[row.id] || []).length"
                  :data="payments[row.id]"
                  size="small"
                  style="width: 100%"
                >
                  <el-table-column label="收款时间" width="150">
                    <template #default="{ row: p }">{{ formatTime(p.paid_at) }}</template>
                  </el-table-column>
                  <el-table-column label="收款金额" width="130" align="right">
                    <template #default="{ row: p }">
                      <span class="amount">¥{{ money(p.amount) }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="收款方式" width="110">
                    <template #default="{ row: p }">{{ p.pay_method || '—' }}</template>
                  </el-table-column>
                  <el-table-column label="来源" width="100">
                    <template #default="{ row: p }">
                      <el-tag
                        :type="PAY_SOURCE_META[p.source]?.type || 'info'"
                        effect="plain"
                        size="small"
                      >
                        {{ PAY_SOURCE_META[p.source]?.label || '线下登记' }}
                      </el-tag>
                    </template>
                  </el-table-column>
                  <el-table-column label="收据号 / 订单号" width="180" show-overflow-tooltip>
                    <template #default="{ row: p }">
                      <span class="mono">{{ p.receipt_no || p.order_no || '—' }}</span>
                    </template>
                  </el-table-column>
                  <el-table-column label="发票" min-width="180">
                    <template #default="{ row: p }">
                      <div class="invoice-cell">
                        <el-tag
                          :type="INVOICE_STATUS_META[p.invoice_status]?.type || 'info'"
                          effect="plain"
                          size="small"
                        >
                          {{ INVOICE_STATUS_META[p.invoice_status]?.label || p.invoice_status }}
                        </el-tag>
                        <span v-if="p.invoice_no" class="invoice-no">{{ p.invoice_no }}</span>
                      </div>
                    </template>
                  </el-table-column>
                  <el-table-column label="操作" width="100" align="center">
                    <template #default="{ row: p }">
                      <el-button link type="primary" @click="openInvoice(p)">发票</el-button>
                    </template>
                  </el-table-column>
                </el-table>

                <el-empty
                  v-else-if="!paymentsLoading[row.id]"
                  description="本期暂无收款记录"
                  :image-size="60"
                />
              </div>
            </template>
          </el-table-column>

          <el-table-column label="期次" width="90" align="center">
            <template #default="{ row }">第 {{ row.period_no }} 期</template>
          </el-table-column>

          <el-table-column label="应收金额" width="130" align="right">
            <template #default="{ row }">
              <span class="amount">¥{{ money(row.due_amount) }}</span>
            </template>
          </el-table-column>

          <el-table-column label="已收金额" width="130" align="right">
            <template #default="{ row }">¥{{ money(row.paid_amount) }}</template>
          </el-table-column>

          <el-table-column label="未收金额" width="130" align="right">
            <template #default="{ row }">
              <span :class="{ unpaid: num(row.unpaid_amount) > 0 }">
                ¥{{ money(row.unpaid_amount) }}
              </span>
            </template>
          </el-table-column>

          <el-table-column label="应收日期" width="120">
            <template #default="{ row }">{{ formatDate(row.due_date) }}</template>
          </el-table-column>

          <el-table-column label="状态" width="140" align="center">
            <template #default="{ row }">
              <div class="status-cell">
                <el-tag :type="periodStatusMeta(row).type" effect="light" size="small">
                  {{ periodStatusMeta(row).label }}
                </el-tag>
                <span v-if="row.status !== 'paid' && row.overdue_days > 0" class="overdue-days">
                  逾期 {{ row.overdue_days }} 天
                </span>
              </div>
            </template>
          </el-table-column>

          <el-table-column label="操作" width="120" align="center" fixed="right">
            <template #default="{ row }">
              <el-button
                link
                type="primary"
                :disabled="num(row.unpaid_amount) <= 0"
                @click="openPayment(row)"
              >
                登记收款
              </el-button>
            </template>
          </el-table-column>
        </el-table>

        <el-empty
          v-if="!detail.periods?.length"
          description="该方案暂无分期期次"
          :image-size="80"
        />
      </el-card>
    </template>

    <!-- 收款登记 -->
    <PaymentDialog v-model="paymentVisible" :period="currentPeriod" @saved="onPaid" />

    <!-- 追加期次 -->
    <el-dialog
      v-model="addVisible"
      title="追加收费期次"
      width="480px"
      :close-on-click-modal="false"
      @closed="resetAdd"
    >
      <el-alert
        title="追加后方案总额将自动同步为各期应收合计"
        type="info"
        :closable="false"
        show-icon
        style="margin-bottom: 16px"
      />
      <el-form ref="addFormRef" :model="addForm" :rules="addRules" label-width="88px">
        <el-form-item label="期次序号" prop="period_no">
          <el-input-number
            v-model="addForm.period_no"
            :min="1"
            :max="99"
            :controls="false"
            placeholder="缺省自动顺延"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="应收金额" prop="due_amount">
          <el-input-number
            v-model="addForm.due_amount"
            :min="0"
            :max="9999999999.99"
            :precision="2"
            :step="10000"
            :controls="false"
            placeholder="0.00"
            style="width: 100%"
          />
        </el-form-item>
        <el-form-item label="应收日期" prop="due_date">
          <el-date-picker
            v-model="addForm.due_date"
            type="date"
            value-format="YYYY-MM-DD"
            placeholder="选择应收日期"
            style="width: 100%"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="addVisible = false">取消</el-button>
        <el-button type="primary" :loading="addSubmitting" @click="submitAdd">确认追加</el-button>
      </template>
    </el-dialog>

    <!-- 发票信息 -->
    <el-dialog
      v-model="invoiceVisible"
      title="登记发票信息"
      width="480px"
      :close-on-click-modal="false"
      @closed="resetInvoice"
    >      <el-form ref="invoiceFormRef" :model="invoiceForm" :rules="invoiceRules" label-width="88px">
        <el-form-item label="发票状态" prop="invoice_status">
          <el-radio-group v-model="invoiceForm.invoice_status">
            <el-radio-button v-for="(m, k) in INVOICE_STATUS_META" :key="k" :value="k">
              {{ m.label }}
            </el-radio-button>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="发票号" prop="invoice_no">
          <el-input
            v-model="invoiceForm.invoice_no"
            placeholder="已开票时必填"
            maxlength="64"
            :disabled="invoiceForm.invoice_status === 'none'"
          />
        </el-form-item>
        <el-form-item label="开票抬头" prop="invoice_title">
          <el-input
            v-model="invoiceForm.invoice_title"
            placeholder="可选"
            maxlength="255"
            :disabled="invoiceForm.invoice_status === 'none'"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="invoiceVisible = false">取消</el-button>
        <el-button type="primary" :loading="invoiceSubmitting" @click="submitInvoice">
          保存
        </el-button>
      </template>
    </el-dialog>

    <!-- 支付订单（对账） -->
    <el-dialog v-model="ordersVisible" title="支付订单" width="920px">
      <div class="orders-tip">
        客户在线支付的订单流水。只有「已支付」的订单才会生成收款记录，失败/过期的订单不会入账。
      </div>
      <el-table :data="orders" v-loading="ordersLoading" size="small" style="width: 100%">
        <el-table-column label="创建时间" width="145">
          <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
        </el-table-column>
        <el-table-column label="期次" width="80" align="center">
          <template #default="{ row }">第 {{ row.period_no }} 期</template>
        </el-table-column>
        <el-table-column label="金额" width="115" align="right">
          <template #default="{ row }">¥{{ money(row.amount) }}</template>
        </el-table-column>
        <el-table-column label="渠道" width="100">
          <template #default="{ row }">{{ row.channel_label }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag
              :type="ORDER_STATUS_META[row.status]?.type || 'info'"
              effect="light"
              size="small"
            >
              {{ ORDER_STATUS_META[row.status]?.label || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="订单号 / 交易号" min-width="200" show-overflow-tooltip>
          <template #default="{ row }">
            <div class="mono">{{ row.order_no }}</div>
            <div class="mono muted">{{ row.transaction_no || '—' }}</div>
          </template>
        </el-table-column>
        <el-table-column label="备注 / 失败原因" min-width="170" show-overflow-tooltip>
          <template #default="{ row }">{{ row.fail_reason || '—' }}</template>
        </el-table-column>
      </el-table>
      <el-empty
        v-if="!ordersLoading && !orders.length"
        description="暂无支付订单"
        :image-size="80"
      />
      <template #footer>
        <el-button @click="ordersVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft, Plus, Tickets } from '@element-plus/icons-vue'
import {
  addFeePeriod,
  getFeePlan,
  listPaymentOrders,
  listPeriodPayments,
  updatePaymentInvoice,
} from '@/api/billing'
import {
  FEE_TYPE_META,
  INVOICE_STATUS_META,
  ORDER_STATUS_META,
  PAY_SOURCE_META,
  formatDate,
  formatTime,
  money,
  num,
  periodStatusMeta,
  planStatusMeta,
  progressPercent,
} from '@/utils/billing'
import PaymentDialog from './PaymentDialog.vue'

const route = useRoute()
const router = useRouter()
const id = Number(route.params.id)

const loading = ref(false)
const detail = ref(null)

const payments = reactive({})
const paymentsLoading = reactive({})

const paymentVisible = ref(false)
const currentPeriod = ref(null)

const addVisible = ref(false)
const addFormRef = ref()
const addSubmitting = ref(false)
const addForm = reactive({ period_no: null, due_amount: null, due_date: '' })

const invoiceVisible = ref(false)
const invoiceFormRef = ref()
const invoiceSubmitting = ref(false)
const currentPayment = ref(null)
const invoiceForm = reactive({ invoice_status: 'none', invoice_no: '', invoice_title: '' })

const ordersVisible = ref(false)
const ordersLoading = ref(false)
const orders = ref([])

const unpaidTotal = computed(() =>
  Math.max(0, num(detail.value?.due_total) - num(detail.value?.paid_total)),
)

const progressColor = computed(() => {
  const p = progressPercent(detail.value?.due_total, detail.value?.paid_total)
  if (p >= 100) return '#1D9E75'
  if (p > 0) return '#c9a55c'
  return '#c0c4cc'
})

const addRules = {
  due_amount: [
    {
      validator: (_r, v, cb) => {
        if (v == null || v === '') return cb(new Error('请输入应收金额'))
        const n = Number(v)
        if (!Number.isFinite(n)) return cb(new Error('请输入正确的金额'))
        if (n <= 0) return cb(new Error('应收金额必须大于 0'))
        if (n > 9999999999.99) return cb(new Error('应收金额不能超过 9999999999.99 元'))
        cb()
      },
      trigger: 'blur',
    },
  ],
}

const invoiceRules = {
  invoice_no: [
    {
      validator: (_r, v, cb) => {
        if (invoiceForm.invoice_status === 'issued' && !(v || '').trim()) {
          return cb(new Error('发票状态为「已开票」时必须填写发票号'))
        }
        cb()
      },
      trigger: 'blur',
    },
  ],
}

async function load() {
  loading.value = true
  try {
    detail.value = await getFeePlan(id)
    // 已展开的期次流水同步刷新
    Object.keys(payments).forEach((pid) => {
      loadPayments(Number(pid))
    })
  } finally {
    loading.value = false
  }
}

async function loadPayments(periodId) {
  paymentsLoading[periodId] = true
  try {
    payments[periodId] = await listPeriodPayments(periodId)
  } finally {
    paymentsLoading[periodId] = false
  }
}

function onExpand(row, expanded) {
  const opened = Array.isArray(expanded) && expanded.some((r) => r.id === row.id)
  if (opened) loadPayments(row.id)
}

function openPayment(row) {
  currentPeriod.value = row
  paymentVisible.value = true
}

function onPaid() {
  load()
}

function openAddPeriod() {
  addForm.period_no = null
  addForm.due_amount = null
  addForm.due_date = ''
  addVisible.value = true
}

function resetAdd() {
  addFormRef.value?.clearValidate()
}

async function submitAdd() {
  await addFormRef.value.validate()
  addSubmitting.value = true
  try {
    const period = await addFeePeriod(id, {
      period_no: addForm.period_no || null,
      due_amount: addForm.due_amount,
      due_date: addForm.due_date || null,
    })
    ElMessage.success(`已追加第 ${period.period_no} 期，方案总额已同步更新`)
    addVisible.value = false
    load()
  } finally {
    addSubmitting.value = false
  }
}

function openInvoice(payment) {
  currentPayment.value = payment
  invoiceForm.invoice_status = payment.invoice_status || 'none'
  invoiceForm.invoice_no = payment.invoice_no || ''
  invoiceForm.invoice_title = payment.invoice_title || ''
  invoiceVisible.value = true
}

function resetInvoice() {
  invoiceFormRef.value?.clearValidate()
}

async function submitInvoice() {
  await invoiceFormRef.value.validate()
  invoiceSubmitting.value = true
  try {
    const payload = {
      invoice_status: invoiceForm.invoice_status,
      invoice_no: (invoiceForm.invoice_no || '').trim() || null,
      invoice_title: (invoiceForm.invoice_title || '').trim() || null,
    }
    const updated = await updatePaymentInvoice(currentPayment.value.id, payload)
    ElMessage.success('发票信息已保存')
    invoiceVisible.value = false
    // 只刷新对应期次的流水，避免整页重载丢失展开状态
    const pid = updated.fee_period_id
    if (payments[pid]) await loadPayments(pid)
  } finally {
    invoiceSubmitting.value = false
  }
}

function back() {
  const base = route.path.startsWith('/admin') ? '/admin' : '/lawyer'
  router.push(`${base}/billing`)
}

async function openOrders() {
  ordersVisible.value = true
  ordersLoading.value = true
  try {
    orders.value = await listPaymentOrders({ plan_id: id })
  } finally {
    ordersLoading.value = false
  }
}

function goCase() {
  const base = route.path.startsWith('/admin') ? '/admin' : '/lawyer'
  router.push(`${base}/cases/${detail.value.case_id}`)
}

load()
</script>

<style scoped>
.billing-detail {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.back-bar {
  margin-bottom: -4px;
}

.section {
  border-radius: 12px;
}

.card-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  color: var(--brand-ink);
}

.plan-head {
  margin-bottom: 18px;
}

.plan-title {
  font-size: 20px;
  font-weight: 600;
  color: var(--brand-ink);
}

.plan-sub {
  margin-top: 8px;
  font-size: 13px;
  color: var(--brand-muted);
  display: flex;
  align-items: center;
}

.desc {
  margin-top: 4px;
}

.amount {
  color: var(--brand-gold-deep);
  font-weight: 600;
}

.unpaid {
  color: var(--el-color-danger);
  font-weight: 600;
}

.progress-box {
  margin-top: 18px;
}

.progress-label {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  color: var(--brand-text);
  margin-bottom: 8px;
}

.progress-num {
  color: var(--brand-muted);
  font-size: 12px;
}

.description-box {
  margin-top: 16px;
  padding: 12px 16px;
  background: var(--brand-bg);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
}

.desc-label {
  color: var(--brand-muted);
  margin-right: 12px;
}

.desc-text {
  color: var(--brand-text);
}

.expand-box {
  padding: 6px 16px 16px 48px;
}

.expand-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  margin-bottom: 10px;
}

.expand-head .sub {
  font-weight: 400;
  color: var(--brand-muted);
}

.invoice-cell {
  display: flex;
  align-items: center;
  gap: 8px;
}

.invoice-no {
  font-size: 12px;
  color: var(--brand-muted);
}

.status-cell {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
}

.overdue-days {
  font-size: 12px;
  color: var(--el-color-danger);
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.pending-alert {
  margin-top: 16px;
  border-radius: 8px;
}

.mono {
  font-family: Consolas, Monaco, monospace;
  font-size: 12px;
}

.muted {
  color: var(--brand-muted);
}

.orders-tip {
  font-size: 12px;
  color: var(--brand-muted);
  margin-bottom: 12px;
  line-height: 1.7;
}
</style>
