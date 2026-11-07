import { defineStore } from 'pinia'

// 全局 AI 悬浮窗（9.8.3）
//
// 用 Pinia 而不是事件总线：案件/合同页的「问 AI」按钮需要把上下文问题带进悬浮窗，
// 而悬浮窗挂在 AppLayout 上，两者没有父子关系。store 里保持 prefillKey 自增，
// 同一句话重复点两次也能重新触发输入框回填。
export const useAiAssistantStore = defineStore('aiAssistant', {
  state: () => ({
    visible: false,
    prefill: '',
    prefillKey: 0,
    // 悬浮窗自己的会话：关掉再打开能接着问，点「新对话」才清空
    sessionId: null,
  }),

  actions: {
    open(text = '') {
      if (text) {
        this.prefill = text
        this.prefillKey += 1
      }
      this.visible = true
    },

    close() {
      this.visible = false
    },

    toggle() {
      if (this.visible) this.close()
      else this.open()
    },

    reset() {
      this.sessionId = null
      this.prefill = ''
    },
  },
})
