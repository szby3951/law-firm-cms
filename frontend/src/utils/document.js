// 文书模块的展示元数据与格式化工具（7.2 文书管理）

import pinia from '@/stores'
import { useDictStore } from '@/stores/dict'

// 文书类型：颜色与图标是前端资产，标签以管理端字典为准
export const DOC_TYPE_META = {
  complaint: { label: '起诉状', color: '#8c2f39', bg: '#f7eaec', icon: 'EditPen' },
  response: { label: '答辩状', color: '#1d4e89', bg: '#e9f0f9', icon: 'ChatLineSquare' },
  agency_argument: { label: '代理词', color: '#7a5c1e', bg: '#f9f2e2', icon: 'Microphone' },
  lawyer_letter: { label: '律师函', color: '#a13f2f', bg: '#fbeeea', icon: 'Promotion' },
  opinion: { label: '法律意见书', color: '#1f5f4a', bg: '#e8f4ef', icon: 'Document' },
  poa: { label: '委托书', color: '#4b3f72', bg: '#eeecf6', icon: 'Files' },
  other: { label: '其他文书', color: '#5b6478', bg: '#eef0f4', icon: 'Tickets' },
}

// 内置兜底候选（字典拉取失败或未加载时使用）
export const DOC_TYPE_OPTIONS = Object.entries(DOC_TYPE_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

// 文书类型候选：以管理端字典为准，未加载时退回内置清单
export function docTypeOptions() {
  const options = useDictStore(pinia).options('doc_type')
  return options.length ? options : DOC_TYPE_OPTIONS
}

/** 触发一次字典加载（组件 setup 里调用；重复调用会自动去重）。 */
export function ensureDocDicts() {
  useDictStore(pinia).ensure()
}

export function docTypeMeta(type) {
  const meta = DOC_TYPE_META[type] || DOC_TYPE_META.other
  // 标签跟随字典，颜色与图标仍按类型编码取前端资产
  return { ...meta, label: useDictStore(pinia).labelOf('doc_type', type, meta.label) }
}

// 文书状态：published 才会出现在客户端
export const DOC_STATUS_META = {
  draft: { label: '草稿', type: 'info', color: '#8a93a6' },
  final: { label: '定稿', type: 'warning', color: '#a5813d' },
  published: { label: '已发布', type: 'success', color: '#2f7d5d' },
}

export const DOC_STATUS_OPTIONS = Object.entries(DOC_STATUS_META).map(([value, meta]) => ({
  value,
  label: meta.label,
}))

export function docStatusMeta(status) {
  return DOC_STATUS_META[status] || { label: status || '—', type: 'info', color: '#8a93a6' }
}

// 模板变量（接口异常时的兜底清单，与后端 TEMPLATE_VARIABLES 一致）
export const FALLBACK_VARIABLES = [
  { key: '客户姓名', desc: '委托客户姓名/机构名称' },
  { key: '客户电话', desc: '客户联系电话' },
  { key: '客户地址', desc: '客户联系地址' },
  { key: '客户证件号', desc: '客户身份证号/统一社会信用代码' },
  { key: '案号', desc: '案件编号' },
  { key: '案件标题', desc: '案件标题' },
  { key: '案由', desc: '案件案由' },
  { key: '受理法院', desc: '受理法院/机构' },
  { key: '对方当事人', desc: '对方当事人' },
  { key: '标的额', desc: '案件标的额（元）' },
  { key: '委托律师', desc: '承办律师姓名' },
  { key: '律所名称', desc: '律师事务所全称' },
  { key: '律所地址', desc: '律所地址' },
  { key: '律所电话', desc: '律所联系电话' },
  { key: '今日日期', desc: '生成当日（2026年11月4日）' },
  { key: '年份', desc: '当前年份' },
  { key: '月份', desc: '当前月份' },
  { key: '日期', desc: '当前日' },
]

// 新文书类型的中性色（未选类型时展示）
export const DOC_TYPE_NEUTRAL = { label: '未分类', color: '#5b6478', bg: '#eef0f4', icon: 'Tickets' }

export function fmtDateTime(value) {
  if (!value) return '—'
  return String(value).replace('T', ' ').slice(0, 16)
}

export function fmtDate(value) {
  if (!value) return '—'
  return String(value).slice(0, 10)
}

// 正文纯文本（列表摘要/搜索兜底）
export function plainText(html) {
  if (!html) return ''
  return String(html)
    .replace(/<(br|\/p|\/div|\/li|\/h[1-6])\s*\/?>/gi, ' ')
    .replace(/<[^>]+>/g, ' ')
    .replace(/&nbsp;/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/\s+/g, ' ')
    .trim()
}

// HTML 归一化：用于「是否有未保存修改」的比较。
// 富文本编辑器（wangEditor）会把 style="text-align:right" 改写成
// style="text-align: right;"，这类纯排版差异不应判定为修改。
export function canonicalHtml(html) {
  if (!html) return ''
  return String(html)
    .replace(/style="([^"]*)"/gi, (_, style) => {
      const normalized = style.replace(/\s+/g, '').replace(/;+$/, '')
      return `style="${normalized}"`
    })
    .replace(/>\s+</g, '><')
    .replace(/\s{2,}/g, ' ')
    .trim()
}

// 模板预览：把 {变量} 高亮成哑光金标签（用于 v-html）
export function highlightVariables(html) {
  if (!html) return ''
  return String(html).replace(
    /\{([^{}\n]{1,20})\}/g,
    (_, key) =>
      `<span style="background:#fbf3e2;color:#a5813d;border:1px solid #ecd9b0;border-radius:3px;padding:0 3px;font-size:.94em;">{${key}}</span>`,
  )
}

// 从 Content-Disposition 解析文件名（后端会带 RFC5987 编码的中文名）
function filenameFromHeaders(headers, fallback) {
  const disposition = headers?.['content-disposition'] || ''
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition)
  if (utf8?.[1]) {
    try {
      return decodeURIComponent(utf8[1])
    } catch {
      /* 解码失败则回退 */
    }
  }
  const plain = /filename="?([^";]+)"?/i.exec(disposition)
  return plain?.[1] ? decodeURIComponent(plain[1]) : fallback
}

// 保存文件流响应为本地文件
export function saveBlobResponse(response, fallbackName = '文书.docx') {
  const blob = response?.data instanceof Blob ? response.data : new Blob([response?.data])
  const name = filenameFromHeaders(response?.headers, fallbackName)
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.appendChild(link)
  link.click()
  link.remove()
  URL.revokeObjectURL(url)
  return name
}
