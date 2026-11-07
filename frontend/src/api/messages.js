import request from './request'
import { saveBlobResponse } from '@/utils/document'

// 沟通留言接口（对应后端 /api/messages/* 与 /api/my/messages/*）
// 律师与管理员共用同一组接口，服务层按登录身份做行级隔离；
// 客户端另有 /my/messages 便于「在线留言」页直接取数据。

// ---------------- 会话 ----------------

export function listConversations(params) {
  return request.get('/messages/conversations', { params })
}

export function getUnreadCount() {
  return request.get('/messages/unread-count')
}

// 会话记录：律师/管理员必须带 client_id，客户可省略
export function listMessages(params) {
  return request.get('/messages', { params })
}

export function sendMessage(data) {
  return request.post('/messages', data)
}

export function markRead(id) {
  return request.patch(`/messages/${id}/read`)
}

// 会话全部已读：clientId 传会话所属客户
export function markConversationRead(clientId) {
  return request.patch(`/messages/conversations/${clientId}/read`)
}

export function markAllRead() {
  return request.patch('/messages/read-all')
}

// ---------------- 附件 ----------------

export function listMessageAttachments(messageId) {
  return request.get(`/messages/${messageId}/attachments`)
}

// 上传附件（先发留言再补传，后端按 message_id 归档）
export function uploadMessageAttachment(messageId, file) {
  const form = new FormData()
  form.append('file', file)
  return request.post(`/messages/${messageId}/attachment`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  })
}

// 附件是带鉴权的，不能直接用 <img src>，需走 axios 取 blob
export function fetchAttachmentBlob(attachmentId) {
  return request.get(`/messages/files/${attachmentId}`, { responseType: 'blob' })
}

export async function downloadAttachment(att, fallbackName = '留言附件') {
  const response = await fetchAttachmentBlob(att.id)
  return saveBlobResponse(response, att?.file_name || fallbackName)
}

// ---------------- 客户端 ----------------

export function listMyMessages(params) {
  return request.get('/my/messages', { params })
}

export function getMyUnreadCount() {
  return request.get('/my/messages/unread-count')
}

export function markMyAllRead() {
  return request.patch('/my/messages/read-all')
}
