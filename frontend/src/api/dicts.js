import request from './request'

// 业务端字典候选（只读，全部登录用户可用）
export function listDictOptions() {
  return request.get('/dicts')
}
