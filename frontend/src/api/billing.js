import request from './request'

// 收费管理接口（对应后端 /api/billing/*）

// 收费方案列表（支持 case_id / status / keyword 筛选）
export function listFeePlans(params) {
  return request.get('/billing/plans', { params })
}

// 收费方案详情（含分期期次）
export function getFeePlan(id) {
  return request.get(`/billing/plans/${id}`)
}

// 创建收费方案（periods 为空则自动生成单期）
export function createFeePlan(data) {
  return request.post('/billing/plans', data)
}

// 追加一期（方案总额自动同步为各期应收合计）
export function addFeePeriod(planId, data) {
  return request.post(`/billing/plans/${planId}/periods`, data)
}

// 某期次的收款流水
export function listPeriodPayments(periodId) {
  return request.get(`/billing/periods/${periodId}/payments`)
}

// 登记收款（支持部分收款，期次状态自动联动）
export function registerPayment(periodId, data) {
  return request.post(`/billing/periods/${periodId}/payments`, data)
}

// 登记/修改发票信息
export function updatePaymentInvoice(paymentId, data) {
  return request.patch(`/billing/payments/${paymentId}/invoice`, data)
}

// 催收清单（已到期未结清）
export function listCollectList(params) {
  return request.get('/billing/collect-list', { params })
}

// 营收统计（year/month 缺省为当月）
export function getBillingStats(params) {
  return request.get('/billing/stats', { params })
}

// ---- 客户端自助 ----
export function listMyBills() {
  return request.get('/my/bills')
}

// ---- 在线缴费（沙箱支付）----

// 发起缴费：创建支付订单（amount 缺省为待缴全额）
export function createPaymentOrder(periodId, data) {
  return request.post(`/my/bills/${periodId}/payment-orders`, data)
}

// 查询支付订单（收银台刷新/轮询）
export function getPaymentOrder(orderNo) {
  return request.get(`/my/payment-orders/${orderNo}`)
}

// 沙箱支付确认（result: success / failed）
export function sandboxPay(orderNo, data) {
  return request.post(`/my/payment-orders/${orderNo}/sandbox-pay`, data)
}

// 取消待支付订单
export function cancelPaymentOrder(orderNo) {
  return request.post(`/my/payment-orders/${orderNo}/cancel`)
}

// 支付订单列表（律师/管理员对账，支持 plan_id/period_id/status）
export function listPaymentOrders(params) {
  return request.get('/billing/orders', { params })
}
