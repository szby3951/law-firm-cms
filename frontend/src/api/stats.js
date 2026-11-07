import request from './request'

// 统计报表接口（模块 10）

// 管理员大屏：全所 KPI、趋势、分布、律师排名、回款、到期与待办
export function getDashboard(params) {
  return request.get('/stats/dashboard', { params })
}

// 律师个人工作台：本人承办案件、客户、创收、日程与待跟进
export function getMyStats(params) {
  return request.get('/stats/my', { params })
}
