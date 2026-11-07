import request from './request'

// AI 能力接口（对应后端 /api/ai/*）
//
// 流式接口一律用 fetch + ReadableStream，不用 axios：
// 1. axios 的 XHR 适配器拿不到增量内容，只能等整个响应结束；
// 2. 统一拦截器设了 30s 超时，而一次合同审查要几十秒到几分钟。
// 因此这里自己建连接，并复用同一套 401 处理。

const BASE = '/api'

function parseBlock(block) {
  const lines = block.split('\n')
  let event = 'message'
  const dataLines = []
  for (const line of lines) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch {
    return null
  }
}

/**
 * 发起一次 SSE POST 请求，按事件回调。
 *
 * @param {string} path 形如 '/ai/review-contract/8'
 * @param {object} body 请求体
 * @param {{ onEvent?: (e: {event: string, data: object}) => void, signal?: AbortSignal }} options
 */
export async function streamPost(path, body, { onEvent, signal } = {}) {
  const token = localStorage.getItem('token')
  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body || {}),
    signal,
  })

  if (!resp.ok) {
    if (resp.status === 401) {
      // 与 axios 拦截器保持一致：清 token 并回登录页
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
      if (!window.location.pathname.startsWith('/login')) {
        window.location.href = '/login'
      }
      throw new Error('登录已过期，请重新登录')
    }
    let detail = `请求失败（HTTP ${resp.status}）`
    try {
      const data = await resp.json()
      if (data?.detail) detail = typeof data.detail === 'string' ? data.detail : detail
    } catch {
      // 非 JSON 错误体，保留默认文案
    }
    throw new Error(detail)
  }
  if (!resp.body) throw new Error('当前浏览器不支持流式响应')

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let index = buffer.indexOf('\n\n')
    while (index >= 0) {
      const block = buffer.slice(0, index)
      buffer = buffer.slice(index + 2)
      const parsed = parseBlock(block)
      if (parsed) onEvent?.(parsed)
      index = buffer.indexOf('\n\n')
    }
  }
}

/**
 * AI 合同风险审查。事件：meta / precheck / warning / stage / progress / done / error。
 * `done` 事件的 data.report 即完整报告，可直接渲染，无需再查合同详情。
 */
export function reviewContract(contractId, body = {}, options = {}) {
  return streamPost(`/ai/review-contract/${contractId}`, body, options)
}

// ---- 问答（9.3）----
/**
 * 法律问答。事件：meta / stage / warning / refs / delta / done / error。
 * `refs` 与 `done.refs` 都含法条原文全文，点击 [n] 时直接按编号取，不必再查接口。
 *
 * 只答法律知识。查自己的案件进度与费用走 `businessChat`——两条链路在服务端
 * 完全分开（不同的提示词、不同的会话类型），不要拿这里的接口去问「我还差多少钱」。
 */
export function chat(body, options = {}) {
  return streamPost('/ai/chat', body, options)
}

// ---- AI督办（9.11）----
/**
 * 业务台账问答。事件：meta / context / stage / delta / done / error。
 *
 * 没有 refs / warning：这一侧不检索法条，答案全部来自业务快照。`context`
 * 事件带本次读取到的数据条目，用于在回答上方渲染「读了哪几条」。
 */
export function businessChat(body, options = {}) {
  return streamPost('/business/chat', body, options)
}

// ---- 会话（9.3）----
export function listAiSessions(params) {
  return request.get('/ai/sessions', { params })
}

/**
 * 会话详情。`type` 为 `chat` / `business` 时后端会校验会话归属，
 * 两个入口的历史不会串到一起（不匹配返回 404）。
 */
export function getAiSession(id, type) {
  return request.get(`/ai/sessions/${id}`, { params: type ? { type } : {} })
}

export function renameAiSession(id, title) {
  return request.patch(`/ai/sessions/${id}`, { title })
}

export function deleteAiSession(id) {
  return request.delete(`/ai/sessions/${id}`)
}

// ---- 文书（9.4）----
export function listDocumentTypes() {
  return request.get('/ai/document-types')
}

// ---- 案件摘要（9.6）----
/**
 * AI 案件摘要。事件：meta / context / warning / stage / delta / done / error。
 * `done` 的 data.content 是 Markdown，data.html 已做转义，可直接渲染。
 */
export function summarizeCase(caseId, body = {}, options = {}) {
  return streamPost(`/ai/case-summary/${caseId}`, body, options)
}

/** 读取本人最近一次生成的摘要；没生成过时 content 为 null。 */
export function getCaseSummary(caseId) {
  return request.get(`/ai/case-summary/${caseId}`)
}
