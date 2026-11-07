<template>
  <AppLayout :menus="menus" home-path="/lawyer" role-label="执业律师" />
</template>

<script setup>
import AppLayout from '@/components/AppLayout.vue'

const menus = [
  { path: '/lawyer', label: '工作台', icon: 'Odometer' },
  { path: '/lawyer/clients', label: '客户管理', icon: 'User' },
  { path: '/lawyer/cases', label: '案件管理', icon: 'Briefcase' },
  { path: '/lawyer/contracts', label: '合同管理', icon: 'Tickets' },
  { path: '/lawyer/billing', label: '收费管理', icon: 'Money' },
  { path: '/lawyer/schedule', label: '日程管理', icon: 'Calendar' },
  { path: '/lawyer/notifications', label: '通知中心', icon: 'Bell' },
  { path: '/lawyer/documents', label: '文书管理', icon: 'Document' },
  { path: '/lawyer/doc-templates', label: '文书模板', icon: 'Collection' },
  { path: '/lawyer/messages', label: '客户留言', icon: 'ChatDotRound' },
  { path: '/lawyer/business', label: 'AI督办', icon: 'DataLine' },
  { path: '/lawyer/ai', label: 'AI 助手', icon: 'MagicStick' },
]
</script>
