// 沟通留言模块的展示工具（8.2 前端）

import { dateKey, toDate } from './schedule'

// 与后端 settings.max_upload_size 保持一致
export const MAX_ATTACHMENT_SIZE = 20 * 1024 * 1024

// 一次最多挂几个附件（前端软限制，避免误选整个文件夹）
export const MAX_ATTACHMENT_COUNT = 5

export const ATTACHMENT_ACCEPT =
  '.pdf,.jpg,.jpeg,.png,.webp,.gif,.doc,.docx,.xls,.xlsx,.txt'

const KIND_META = {
  image: { label: '图片', icon: 'Picture', color: '#1f5f4a', bg: '#e8f4ef' },
  pdf: { label: 'PDF', icon: 'Document', color: '#8c2f39', bg: '#f7eaec' },
  word: { label: 'Word', icon: 'Tickets', color: '#1d4e89', bg: '#e9f0f9' },
  excel: { label: 'Excel', icon: 'Grid', color: '#1f5f4a', bg: '#e8f4ef' },
  file: { label: '文件', icon: 'Files', color: '#5b6478', bg: '#eef0f4' },
}

const EXT_KIND = {
  jpg: 'image',
  jpeg: 'image',
  png: 'image',
  webp: 'image',
  gif: 'image',
  bmp: 'image',
  pdf: 'pdf',
  doc: 'word',
  docx: 'word',
  xls: 'excel',
  xlsx: 'excel',
}

// 附件类型元数据：按扩展名判断，拿不到再退回 mime
export function attachmentMeta(att) {
  const name = String(att?.file_name || '')
  const ext = name.includes('.') ? name.split('.').pop().toLowerCase() : ''
  let kind = EXT_KIND[ext]

  if (!kind) {
    const mime = String(att?.mime_type || '')
    if (mime.startsWith('image/')) kind = 'image'
    else if (mime === 'application/pdf') kind = 'pdf'
    else if (mime.includes('word')) kind = 'word'
    else if (mime.includes('excel') || mime.includes('spreadsheet')) kind = 'excel'
  }

  const meta = KIND_META[kind] || KIND_META.file
  return { ...meta, kind: kind || 'file', ext: ext.toUpperCase() }
}

// 图片 / PDF 可在线预览，其余走下载
export function isPreviewable(att) {
  const kind = attachmentMeta(att).kind
  return kind === 'image' || kind === 'pdf'
}

export function fmtFileSize(bytes) {
  const n = Number(bytes)
  if (!Number.isFinite(n) || n < 0) return '—'
  if (n < 1024) return `${n} B`
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 / 1024).toFixed(1)} MB`
}

export function initials(name) {
  const text = String(name || '').trim()
  return text ? text.slice(0, 1) : '?'
}

// 聊天日期分隔：今天 / 昨天 / 11月3日 / 2025年11月3日
export function dayLabel(value) {
  const d = toDate(value)
  if (!d) return ''
  const today = new Date()
  const todayKey = dateKey(today)
  const yest = new Date(today.getFullYear(), today.getMonth(), today.getDate() - 1)
  const key = dateKey(d)
  if (key === todayKey) return '今天'
  if (key === dateKey(yest)) return '昨天'
  if (d.getFullYear() === today.getFullYear()) {
    return `${d.getMonth() + 1}月${d.getDate()}日`
  }
  return `${d.getFullYear()}年${d.getMonth() + 1}月${d.getDate()}日`
}

export function senderRoleLabel(role) {
  return role === 'client' ? '客户' : '律师'
}
