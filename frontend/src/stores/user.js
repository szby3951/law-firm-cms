import { defineStore } from 'pinia'
import { getMe, login as apiLogin } from '@/api/auth'

// 用户状态：token / 用户信息 / 角色，持久化到 localStorage
export const useUserStore = defineStore('user', {
  state: () => ({
    token: localStorage.getItem('token') || '',
    userInfo: JSON.parse(localStorage.getItem('userInfo') || 'null'),
  }),

  getters: {
    isLoggedIn: (state) => !!state.token,
    role: (state) => state.userInfo?.role || '',
    realName: (state) => state.userInfo?.real_name || state.userInfo?.username || '',
  },

  actions: {
    async login(payload) {
      const data = await apiLogin(payload)
      this.token = data.access_token
      this.userInfo = data.user
      localStorage.setItem('token', data.access_token)
      localStorage.setItem('userInfo', JSON.stringify(data.user))
      return data
    },

    async fetchUserInfo() {
      const user = await getMe()
      this.userInfo = user
      localStorage.setItem('userInfo', JSON.stringify(user))
      return user
    },

    logout() {
      this.token = ''
      this.userInfo = null
      localStorage.removeItem('token')
      localStorage.removeItem('userInfo')
    },
  },
})
