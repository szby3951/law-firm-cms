import request from './request'

// 站内通知接口（对应后端 /api/notifications/* 与 /api/my/notifications/*）

// ---- 律师 / 管理员 ----
export function listNotifications(params) {
  return request.get('/notifications', { params })
}

export function getUnreadCount() {
  return request.get('/notifications/unread-count')
}

export function markRead(id) {
  return request.patch(`/notifications/${id}/read`)
}

export function markAllRead() {
  return request.patch('/notifications/read-all')
}

export function deleteNotification(id) {
  return request.delete(`/notifications/${id}`)
}

// 手动触发一轮提醒扫描（仅管理员，验收/补推用）
export function scanReminders() {
  return request.post('/notifications/scan')
}

// ---- 客户端（仅本人相关的对外通知）----
export function listMyNotifications(params) {
  return request.get('/my/notifications', { params })
}

export function getMyUnreadCount() {
  return request.get('/my/notifications/unread-count')
}

export function markMyRead(id) {
  return request.patch(`/my/notifications/${id}/read`)
}

export function markMyAllRead() {
  return request.patch('/my/notifications/read-all')
}
