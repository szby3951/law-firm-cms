import request from './request'

// 文书管理接口（对应后端 /api/documents/*）

export function listDocuments(params) {
  return request.get('/documents', { params })
}

export function getDocument(id) {
  return request.get(`/documents/${id}`)
}

export function createDocument(data) {
  return request.post('/documents', data)
}

export function updateDocument(id, data) {
  return request.put(`/documents/${id}`, data)
}

export function deleteDocument(id) {
  return request.delete(`/documents/${id}`)
}

// 按模板生成草稿：只返回填充结果，不落库（前端在编辑器确认后再保存）
export function generateDocument(data) {
  return request.post('/documents/generate', data)
}

// 导出 docx：生成文件并返回下载地址
export function exportDocument(id) {
  return request.post(`/documents/${id}/export`)
}

// 下载 docx（文件流，需取 response.data）
export function downloadDocument(id) {
  return request.get(`/documents/${id}/download`, { responseType: 'blob' })
}

// ---------------- 文书模板 ----------------

export function listDocTemplates(params) {
  return request.get('/doc-templates', { params })
}

export function getDocTemplate(id) {
  return request.get(`/doc-templates/${id}`)
}

export function createDocTemplate(data) {
  return request.post('/doc-templates', data)
}

export function updateDocTemplate(id, data) {
  return request.put(`/doc-templates/${id}`, data)
}

export function deleteDocTemplate(id) {
  return request.delete(`/doc-templates/${id}`)
}

// 模板可用变量清单
export function listTemplateVariables() {
  return request.get('/doc-templates/variables')
}

// ---------------- 客户端：我的文书 ----------------

export function listMyDocuments(params) {
  return request.get('/my/documents', { params })
}

export function getMyDocument(id) {
  return request.get(`/my/documents/${id}`)
}

export function downloadMyDocument(id) {
  return request.get(`/my/documents/${id}/download`, { responseType: 'blob' })
}
