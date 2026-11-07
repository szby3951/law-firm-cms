import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

// 角色 → 默认首页映射（登录后按角色重定向）
const ROLE_HOME = {
  client: '/client',
  lawyer: '/lawyer',
  admin: '/admin',
}

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/auth/Login.vue'),
    meta: { public: true, title: '登录' },
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/auth/Register.vue'),
    meta: { public: true, title: '注册' },
  },
  {
    path: '/client',
    component: () => import('@/layouts/ClientLayout.vue'),
    meta: { roles: ['client'] },
    children: [
      {
        path: '',
        name: 'ClientHome',
        component: () => import('@/views/client/Home.vue'),
        meta: { title: '首页', sub: '委托概览 · 待办提醒' },
      },
      {
        path: 'cases',
        name: 'ClientCaseList',
        component: () => import('@/views/client/MyCases.vue'),
        meta: { title: '我的案件' },
      },
      {
        path: 'cases/:id',
        name: 'ClientCaseDetail',
        component: () => import('@/views/client/MyCaseDetail.vue'),
        meta: { title: '案件详情', sub: '案件进展 · 时间线' },
      },
      {
        path: 'contracts',
        name: 'ClientContracts',
        component: () => import('@/views/client/MyContracts.vue'),
        meta: { title: '我的合同' },
      },
      {
        path: 'contracts/:id',
        name: 'ClientContractDetail',
        component: () => import('@/views/client/MyContractDetail.vue'),
        meta: { title: '合同详情', sub: '合同信息 · 文件 · 审查报告' },
      },
      {
        path: 'bills',
        name: 'ClientBills',
        component: () => import('@/views/client/MyBills.vue'),
        meta: { title: '我的账单', sub: '应收 · 已缴 · 发票状态' },
      },
      {
        path: 'notifications',
        name: 'ClientNotifications',
        component: () => import('@/views/client/Notifications.vue'),
        meta: { title: '消息通知', sub: '开庭 · 期限 · 缴费提醒' },
      },
      {
        path: 'documents',
        name: 'ClientDocuments',
        component: () => import('@/views/client/MyDocuments.vue'),
        meta: { title: '我的文书', sub: '律师发布的文书 · 在线查看 · 下载' },
      },
      {
        path: 'messages',
        name: 'ClientMessages',
        component: () => import('@/views/client/Messages.vue'),
        meta: { title: '在线留言', sub: '与承办律师沟通 · 材料随留言上传' },
      },
      {
        path: 'ai',
        name: 'ClientAi',
        component: () => import('@/views/client/AiAssistant.vue'),
        meta: { title: 'AI 法律问答', sub: '基础问答 · 法条解释 · 仅供参考' },
      },
      {
        path: 'business',
        name: 'ClientBusiness',
        component: () => import('@/views/client/MyBusiness.vue'),
        meta: { title: 'AI督办', sub: '进度跟踪 · 费用缴纳 · 开庭提醒' },
      },
    ],
  },
  {
    path: '/lawyer',
    component: () => import('@/layouts/LawyerLayout.vue'),
    meta: { roles: ['lawyer', 'admin'] },
    children: [
      {
        path: '',
        name: 'LawyerHome',
        component: () => import('@/views/lawyer/Home.vue'),
        meta: { title: '工作台' },
      },
      {
        path: 'clients',
        name: 'LawyerClients',
        component: () => import('@/views/lawyer/ClientList.vue'),
        meta: { title: '客户管理', sub: '客户档案与跟进记录' },
      },
      {
        path: 'clients/:id',
        name: 'LawyerClientDetail',
        component: () => import('@/views/lawyer/ClientDetail.vue'),
        meta: { title: '客户详情', sub: '基本信息 · 跟进时间线 · 关联案件' },
      },
      {
        path: 'cases',
        name: 'LawyerCases',
        component: () => import('@/views/lawyer/CaseList.vue'),
        meta: { title: '案件管理', sub: '案件台账与生命周期' },
      },
      {
        path: 'cases/:id',
        name: 'LawyerCaseDetail',
        component: () => import('@/views/lawyer/CaseDetail.vue'),
        meta: { title: '案件详情', sub: '基本信息 · 时间线 · 承办律师' },
      },
      {
        path: 'contracts',
        name: 'LawyerContracts',
        component: () => import('@/views/lawyer/ContractList.vue'),
        meta: { title: '合同管理', sub: '合同台账 · 到期预警' },
      },
      {
        path: 'contracts/:id',
        name: 'LawyerContractDetail',
        component: () => import('@/views/lawyer/ContractDetail.vue'),
        meta: { title: '合同详情', sub: '合同信息 · 文件 · 审查报告' },
      },
      {
        path: 'billing',
        name: 'LawyerBilling',
        component: () => import('@/views/lawyer/BillingList.vue'),
        meta: { title: '收费管理', sub: '收费方案 · 分期收款 · 催收' },
      },
      {
        path: 'billing/collect',
        name: 'LawyerCollectList',
        component: () => import('@/views/lawyer/CollectList.vue'),
        meta: { title: '催收清单', sub: '已到期未结清的账单' },
      },
      {
        path: 'billing/:id',
        name: 'LawyerBillingDetail',
        component: () => import('@/views/lawyer/BillingDetail.vue'),
        meta: { title: '收费方案详情', sub: '分期计划 · 收款流水 · 发票' },
      },
      {
        path: 'schedule',
        name: 'LawyerSchedule',
        component: () => import('@/views/lawyer/Schedule.vue'),
        meta: { title: '日程管理', sub: '日历视图 · 今日待办 · 提醒' },
      },
      {
        path: 'notifications',
        name: 'LawyerNotifications',
        component: () => import('@/views/lawyer/Notifications.vue'),
        meta: { title: '通知中心', sub: '开庭 · 缴费 · 跟进 · 合同提醒' },
      },
      {
        path: 'documents',
        name: 'LawyerDocuments',
        component: () => import('@/views/lawyer/DocumentList.vue'),
        meta: { title: '文书管理', sub: '文书库 · 模板生成 · docx 导出' },
      },
      {
        path: 'documents/:id',
        name: 'LawyerDocumentEditor',
        component: () => import('@/views/lawyer/DocumentEditor.vue'),
        meta: { title: '文书编辑', sub: '在线编辑 · 模板变量 · 导出 docx' },
      },
      {
        path: 'doc-templates',
        name: 'LawyerDocTemplates',
        component: () => import('@/views/lawyer/TemplateManage.vue'),
        meta: { title: '文书模板', sub: '模板库 · 变量占位 · 全所共享' },
      },
      {
        path: 'messages',
        name: 'LawyerMessages',
        component: () => import('@/views/lawyer/Messages.vue'),
        meta: { title: '客户留言', sub: '会话列表 · 回复客户 · 附件收发' },
      },
      {
        path: 'ai',
        name: 'LawyerAi',
        component: () => import('@/views/ai/AiAssistant.vue'),
        meta: { title: 'AI 法律助手', sub: 'RAG 问答 · 法条引用 · 场景直达' },
      },
      {
        path: 'business',
        name: 'LawyerBusiness',
        component: () => import('@/views/ai/MyBusiness.vue'),
        meta: { title: 'AI督办', sub: '进度跟踪 · 待收款 · 节点提醒' },
      },
    ],
  },
  {
    path: '/admin',
    component: () => import('@/layouts/AdminLayout.vue'),
    meta: { roles: ['admin'] },
    children: [
      {
        path: '',
        name: 'AdminDashboard',
        component: () => import('@/views/admin/Dashboard.vue'),
        meta: { title: '统计大屏', sub: '运营概览 · 数据可视化' },
      },
      {
        path: 'clients',
        name: 'AdminClients',
        component: () => import('@/views/lawyer/ClientList.vue'),
        meta: { title: '客户管理', sub: '客户档案与跟进记录' },
      },
      {
        path: 'clients/:id',
        name: 'AdminClientDetail',
        component: () => import('@/views/lawyer/ClientDetail.vue'),
        meta: { title: '客户详情', sub: '基本信息 · 跟进时间线 · 关联案件' },
      },
      {
        path: 'cases',
        name: 'AdminCases',
        component: () => import('@/views/lawyer/CaseList.vue'),
        meta: { title: '案件与分案', sub: '案件台账 · 分案管理' },
      },
      {
        path: 'cases/:id',
        name: 'AdminCaseDetail',
        component: () => import('@/views/lawyer/CaseDetail.vue'),
        meta: { title: '案件详情', sub: '基本信息 · 时间线 · 分案' },
      },
      {
        path: 'contracts',
        name: 'AdminContracts',
        component: () => import('@/views/lawyer/ContractList.vue'),
        meta: { title: '合同管理', sub: '合同台账 · 到期预警' },
      },
      {
        path: 'contracts/:id',
        name: 'AdminContractDetail',
        component: () => import('@/views/lawyer/ContractDetail.vue'),
        meta: { title: '合同详情', sub: '合同信息 · 文件 · 审查报告' },
      },
      {
        path: 'billing',
        name: 'AdminBilling',
        component: () => import('@/views/lawyer/BillingList.vue'),
        meta: { title: '收费管理', sub: '全所收费方案 · 分期收款 · 催收' },
      },
      {
        path: 'billing/collect',
        name: 'AdminCollectList',
        component: () => import('@/views/lawyer/CollectList.vue'),
        meta: { title: '催收清单', sub: '已到期未结清的账单' },
      },
      {
        path: 'billing/:id',
        name: 'AdminBillingDetail',
        component: () => import('@/views/lawyer/BillingDetail.vue'),
        meta: { title: '收费方案详情', sub: '分期计划 · 收款流水 · 发票' },
      },
      {
        path: 'schedule',
        name: 'AdminSchedule',
        component: () => import('@/views/lawyer/Schedule.vue'),
        meta: { title: '日程管理', sub: '全所日程 · 日历视图 · 提醒' },
      },
      {
        path: 'notifications',
        name: 'AdminNotifications',
        component: () => import('@/views/lawyer/Notifications.vue'),
        meta: { title: '通知中心', sub: '提醒消息 · 手动补扫' },
      },
      {
        path: 'documents',
        name: 'AdminDocuments',
        component: () => import('@/views/lawyer/DocumentList.vue'),
        meta: { title: '文书管理', sub: '全所文书 · 模板生成 · docx 导出' },
      },
      {
        path: 'documents/:id',
        name: 'AdminDocumentEditor',
        component: () => import('@/views/lawyer/DocumentEditor.vue'),
        meta: { title: '文书编辑', sub: '在线编辑 · 模板变量 · 导出 docx' },
      },
      {
        path: 'doc-templates',
        name: 'AdminDocTemplates',
        component: () => import('@/views/lawyer/TemplateManage.vue'),
        meta: { title: '文书模板', sub: '模板库 · 变量占位 · 全所共享' },
      },
      {
        path: 'messages',
        name: 'AdminMessages',
        component: () => import('@/views/lawyer/Messages.vue'),
        meta: { title: '沟通留言', sub: '全所会话 · 回复客户 · 附件收发' },
      },
      {
        path: 'ai',
        name: 'AdminAi',
        component: () => import('@/views/ai/AiAssistant.vue'),
        meta: { title: 'AI 法律助手', sub: 'RAG 问答 · 法条引用 · 场景直达' },
      },
      {
        path: 'business',
        name: 'AdminBusiness',
        component: () => import('@/views/ai/MyBusiness.vue'),
        meta: { title: 'AI督办', sub: '全所案件 · 应收 · 节点提醒' },
      },
      {
        path: 'users',
        name: 'AdminUsers',
        component: () => import('@/views/admin/UserManage.vue'),
        meta: { title: '账号管理', sub: '律师账号开通 · 禁用 · 重置密码' },
      },
      {
        path: 'logs',
        name: 'AdminLogs',
        component: () => import('@/views/admin/Logs.vue'),
        meta: { title: '操作日志', sub: '登录 · 增删改 · 导出全程留痕' },
      },
      {
        path: 'settings',
        name: 'AdminSettings',
        component: () => import('@/views/admin/Settings.vue'),
        meta: { title: '系统设置', sub: '数据字典 · 律所信息 · AI 配置' },
      },
    ],
  },
  { path: '/', redirect: '/login' },
  { path: '/:pathMatch(.*)*', redirect: '/login' },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

// 全局守卫：未登录跳登录；已登录按角色放行/重定向
router.beforeEach((to) => {
  const userStore = useUserStore()

  // 公开页面直接放行
  if (to.meta.public) {
    return true
  }

  // 未登录 → 登录页
  if (!userStore.isLoggedIn) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }

  // 已登录访问登录页 → 回各自首页
  if (to.name === 'Login') {
    return { path: ROLE_HOME[userStore.role] || '/login' }
  }

  // 角色校验：目标路由要求的角色
  const roles = to.meta.roles
  if (roles && !roles.includes(userStore.role)) {
    return { path: ROLE_HOME[userStore.role] || '/login' }
  }

  return true
})

router.afterEach((to) => {
  document.title = to.meta.title
    ? `${to.meta.title} · 律所客户智能管理系统`
    : '律所客户智能管理系统'
})

export default router
