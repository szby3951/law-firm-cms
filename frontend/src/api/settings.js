import request from './request'

// 系统设置接口（模块 11.1.5）：数据字典、律所信息、AI 配置

// 字典列表：dict_type 可选，返回 items + types
export function listDicts(params) {
  return request.get('/admin/dicts', { params })
}

export function createDict(data) {
  return request.post('/admin/dicts', data)
}

export function updateDict(id, data) {
  return request.put(`/admin/dicts/${id}`, data)
}

export function deleteDict(id) {
  return request.delete(`/admin/dicts/${id}`)
}

// 律所信息（单行）
export function getFirm() {
  return request.get('/admin/firm')
}

export function updateFirm(data) {
  return request.put('/admin/firm', data)
}

// AI 配置：返回的 api_key 已脱敏，改动时留空表示不修改
export function getAiConfig() {
  return request.get('/admin/ai-config')
}

export function updateAiConfig(data) {
  return request.put('/admin/ai-config', data)
}
