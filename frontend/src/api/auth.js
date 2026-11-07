import request from './request'

// 认证与权限接口（对应后端 /api/auth/*）
export function login(data) {
  return request.post('/auth/login', data)
}

export function register(data) {
  return request.post('/auth/register', data)
}

export function getMe() {
  return request.get('/auth/me')
}
