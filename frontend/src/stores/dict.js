import { defineStore } from 'pinia'
import { listDictOptions } from '@/api/dicts'

// 数据字典候选：全站共享一份，登录后首次使用拉取，之后走内存
export const useDictStore = defineStore('dict', {
  state: () => ({
    dicts: {},
    loaded: false,
    pending: null,
  }),

  getters: {
    // 某分类的候选：[{ label, value }]，未加载时为空数组
    options: (state) => (type) => state.dicts[type] || [],
  },

  actions: {
    /**
     * 确保字典已加载。
     * @param {boolean} force 强制重新拉取（管理端改完字典后使用）
     */
    async ensure(force = false) {
      if (this.loaded && !force) return this.dicts
      if (this.pending) return this.pending
      this.pending = listDictOptions()
        .then((data) => {
          this.dicts = data?.dicts || {}
          this.loaded = true
          return this.dicts
        })
        .catch(() => {
          // 拉取失败不阻断页面：下拉退化为可手工输入 / 空列表
          this.dicts = {}
          this.loaded = true
          return this.dicts
        })
        .finally(() => {
          this.pending = null
        })
      return this.pending
    },

    /** 取显示标签：字典里没有该值时用 fallback（再退回原值）。 */
    labelOf(type, value, fallback = '') {
      if (!value) return fallback
      const hit = (this.dicts[type] || []).find((o) => o.value === value)
      return hit ? hit.label : fallback || value
    },
  },
})
