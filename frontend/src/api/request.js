import axios from 'axios'
import { ElMessage } from 'element-plus'
import router from '@/router'

// 统一请求实例：baseURL 走 vite 代理（/api → 后端 8000）
const request = axios.create({
  baseURL: '/api',
  timeout: 30000,
})

// 请求拦截器：自动携带 Token
request.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error),
)

// 响应拦截器：统一解包与错误处理
request.interceptors.response.use(
  (response) => {
    // 文件流等二进制响应直接透传
    if (response.config.responseType === 'blob') {
      return response
    }
    return response.data
  },
  (error) => {
    const status = error.response?.status
    const detail = error.response?.data?.detail

    if (status === 401) {
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
      ElMessage.error('登录已过期，请重新登录')
      router.push('/login')
    } else if (status === 403) {
      ElMessage.error(typeof detail === 'string' ? detail : '没有操作权限')
    } else if (status === 404) {
      ElMessage.error('请求的资源不存在')
    } else if (status >= 500) {
      ElMessage.error('服务器开小差了，请稍后重试')
    } else if (detail) {
      ElMessage.error(typeof detail === 'string' ? detail : JSON.stringify(detail))
    }

    return Promise.reject(error)
  },
)

export default request
