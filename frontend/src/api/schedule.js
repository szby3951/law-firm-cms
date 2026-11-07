import request from './request'

// 日程管理接口（对应后端 /api/schedule/*）

// 日历数据：区间内按天分组，供月/周/日视图渲染
export function getScheduleCalendar(params) {
  return request.get('/schedule/calendar', { params })
}

// 今日日程（首页待办）
export function getTodaySchedules() {
  return request.get('/schedule/today')
}

// 未来 N 天待办日程
export function getUpcomingSchedules(days = 7) {
  return request.get('/schedule/upcoming', { params: { days } })
}

// 日程分页列表（支持区间/类型/状态/案件/关键词）
export function listSchedules(params) {
  return request.get('/schedule', { params })
}

export function getSchedule(id) {
  return request.get(`/schedule/${id}`)
}

export function createSchedule(data) {
  return request.post('/schedule', data)
}

// 全量更新（未传的可空字段会被清空）
export function updateSchedule(id, data) {
  return request.put(`/schedule/${id}`, data)
}

// 标记状态：pending / done / cancelled
export function updateScheduleStatus(id, status) {
  return request.patch(`/schedule/${id}/status`, { status })
}

export function deleteSchedule(id) {
  return request.delete(`/schedule/${id}`)
}
