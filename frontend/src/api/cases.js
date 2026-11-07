import request from './request'

// 案件管理接口（对应后端 /api/cases/*）

export function listCases(params) {
  return request.get('/cases', { params })
}

export function getCase(id) {
  return request.get(`/cases/${id}`)
}

export function createCase(data) {
  return request.post('/cases', data)
}

// 删除案件（仅管理员）
export function deleteCase(id) {
  return request.delete(`/cases/${id}`)
}

// 分案（仅管理员）
export function assignCase(id, data) {
  return request.post(`/cases/${id}/assign`, data)
}

// 状态流转
export function updateCaseStatus(id, status) {
  return request.patch(`/cases/${id}/status`, { status })
}

// 登记案件事件
export function addCaseEvent(id, data) {
  return request.post(`/cases/${id}/events`, data)
}

// 上传案件文件（multipart）
export function uploadCaseFile(id, file) {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/cases/${id}/files`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
}

// 下载/预览案件材料（返回 blob）
export function downloadCaseFile(attachmentId) {
  return request.get(`/cases/files/${attachmentId}`, { responseType: 'blob' })
}

// 律师列表（供分案选择，仅管理员）
export function listLawyers() {
  return request.get('/cases/lawyers')
}

// ---- 客户端自助 ----
export function listMyCases() {
  return request.get('/my/cases')
}

export function getMyCase(id) {
  return request.get(`/my/cases/${id}`)
}
