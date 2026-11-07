import request from './request'

// 系统管理接口（模块 11）：账号管理、操作日志

// 账号列表：role/keyword/status/page/page_size
export function listUsers(params) {
  return request.get('/admin/users', { params })
}

// 开通律师账号
export function createLawyer(data) {
  return request.post('/admin/users/lawyers', data)
}

// 启用/禁用账号（1=正常 0=禁用）
export function updateUserStatus(id, status) {
  return request.patch(`/admin/users/${id}/status`, { status })
}

// 重置账号密码
export function resetUserPassword(id, newPassword) {
  return request.post(`/admin/users/${id}/reset-password`, { new_password: newPassword })
}

// 操作日志：action/keyword/user_id/start/end/page/page_size
export function listLogs(params) {
  return request.get('/admin/logs', { params })
}
