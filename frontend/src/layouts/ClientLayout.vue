<template>
  <AppLayout :menus="menus" home-path="/client" role-label="客户" />
</template>

<script setup>
import AppLayout from '@/components/AppLayout.vue'

const menus = [
  { path: '/client', label: '首页', icon: 'HomeFilled' },
  { path: '/client/cases', label: '我的案件', icon: 'Files' },
  { path: '/client/contracts', label: '我的合同', icon: 'Tickets' },
  { path: '/client/bills', label: '我的账单', icon: 'Money' },
  { path: '/client/notifications', label: '消息通知', icon: 'Bell' },
  { path: '/client/documents', label: '我的文书', icon: 'Document' },
  { path: '/client/messages', label: '在线留言', icon: 'ChatDotRound' },
  { path: '/client/business', label: 'AI督办', icon: 'DataLine' },
  { path: '/client/ai', label: 'AI 法律问答', icon: 'MagicStick' },
]
</script>
