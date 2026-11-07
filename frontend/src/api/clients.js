import request from './request'

// 客户关系管理接口（对应后端 /api/clients/*）

export function listClients(params) {
  return request.get('/clients', { params })
}

export function getClient(id) {
  return request.get(`/clients/${id}`)
}

export function createClient(data) {
  return request.post('/clients', data)
}

export function updateClient(id, data) {
  return request.put(`/clients/${id}`, data)
}

export function deleteClient(id) {
  return request.delete(`/clients/${id}`)
}

// 跟进记录
export function addFollow(id, data) {
  return request.post(`/clients/${id}/follows`, data)
}

export function listFollows(id) {
  return request.get(`/clients/${id}/follows`)
}

// AI 客户画像（9.7）：生成是一次性 JSON，模型要读完客户全部数据，
// 默认 30 秒会误判超时，这里单独放宽到 120 秒
export function getClientProfile(id) {
  return request.get(`/clients/${id}/ai-profile`)
}

export function generateClientProfile(id, data) {
  return request.post(`/clients/${id}/ai-profile`, data, { timeout: 120000 })
}

// 导出 Excel（返回二进制流）
export function exportClients(params) {
  return request.get('/clients/export', {
    params,
    responseType: 'blob',
  })
}
