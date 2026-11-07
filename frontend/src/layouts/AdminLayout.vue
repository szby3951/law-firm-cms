<template>
  <AppLayout :menus="menus" home-path="/admin" role-label="管理员" />
</template>

<script setup>
import AppLayout from '@/components/AppLayout.vue'

const menus = [
  { path: '/admin', label: '统计大屏', icon: 'DataAnalysis' },
  { path: '/admin/clients', label: '客户管理', icon: 'User' },
  { path: '/admin/cases', label: '案件与分案', icon: 'Briefcase' },
  { path: '/admin/contracts', label: '合同管理', icon: 'Tickets' },
  { path: '/admin/billing', label: '收费管理', icon: 'Money' },
  { path: '/admin/schedule', label: '日程管理', icon: 'Calendar' },
  { path: '/admin/documents', label: '文书管理', icon: 'Document' },
  { path: '/admin/doc-templates', label: '文书模板', icon: 'Collection' },
  { path: '/admin/notifications', label: '通知中心', icon: 'Bell' },
  { path: '/admin/messages', label: '沟通留言', icon: 'ChatDotRound' },
  { path: '/admin/business', label: 'AI督办', icon: 'DataLine' },
  { path: '/admin/ai', label: 'AI 助手', icon: 'MagicStick' },
  { path: '/admin/users', label: '账号管理', icon: 'Avatar' },
  { path: '/admin/logs', label: '操作日志', icon: 'List' },
  { path: '/admin/settings', label: '系统设置', icon: 'Setting' },
]
</script>
