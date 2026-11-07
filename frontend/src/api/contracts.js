import request from './request'

// 合同管理接口（对应后端 /api/contracts/*）

export function listContracts(params) {
  return request.get('/contracts', { params })
}

export function getContract(id) {
  return request.get(`/contracts/${id}`)
}

export function createContract(data) {
  return request.post('/contracts', data)
}

export function updateContract(id, data) {
  return request.put(`/contracts/${id}`, data)
}

// 到期预警（days：未来 N 天内到期）
export function listExpiringContracts(days = 30) {
  return request.get('/contracts/expiring', { params: { days } })
}

// 上传合同文件（multipart）
export function uploadContractFile(id, file) {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/contracts/${id}/upload`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// 下载合同文件（返回 blob）
export function downloadContractFile(id) {
  return request.get(`/contracts/${id}/download`, { responseType: 'blob' })
}

// 保存 AI 审查报告
export function saveContractReview(id, report) {
  return request.post(`/contracts/${id}/review`, { report })
}

// ---- 客户端自助 ----
export function listMyContracts() {
  return request.get('/my/contracts')
}

export function getMyContract(id) {
  return request.get(`/my/contracts/${id}`)
}
