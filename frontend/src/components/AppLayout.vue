<template>
  <el-container class="app-layout">
    <!-- ============ 侧边栏：深色商务 ============ -->
    <el-aside :width="collapsed ? '64px' : '220px'" class="aside">
      <div class="brand-area" @click="$router.push(homePath)">
        <BrandLogo :compact="collapsed" small />
      </div>

      <el-scrollbar class="menu-scroll">
        <el-menu
          :default-active="activePath"
          :collapse="collapsed"
          :collapse-transition="false"
          router
          class="menu"
        >
          <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
            <el-icon><component :is="m.icon" /></el-icon>
            <template #title>{{ m.label }}</template>
          </el-menu-item>
        </el-menu>
      </el-scrollbar>

      <div class="aside-foot" @click="collapsed = !collapsed">
        <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
        <span v-if="!collapsed">收起导航</span>
      </div>
    </el-aside>

    <!-- ============ 右侧：顶栏 + 内容 ============ -->
    <el-container class="right">
      <el-header class="header" height="60px">
        <div class="header-left">
          <div class="page-title">{{ pageTitle }}</div>
          <div class="page-sub">{{ pageSub }}</div>
        </div>

        <div class="header-right">
          <NotificationBell />

          <el-dropdown trigger="click" @command="onCommand">
            <div class="user-chip">
              <div class="avatar">{{ avatarText }}</div>
              <div class="meta">
                <div class="name">{{ userStore.realName }}</div>
                <div class="role">{{ roleLabel }}</div>
              </div>
              <el-icon class="caret"><ArrowDown /></el-icon>
            </div>
            <template #dropdown>
              <el-dropdown-menu>
                <div class="drop-head">
                  <div class="drop-name">{{ userStore.userInfo?.real_name }}</div>
                  <div class="drop-account">{{ userStore.userInfo?.username }}</div>
                </div>
                <el-dropdown-item divided command="logout">
                  <el-icon><SwitchButton /></el-icon>退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>

    <!-- 全局 AI 悬浮窗（9.8.3）：任何业务页右下角可唤起 -->
    <AiAssistantLauncher />
  </el-container>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import BrandLogo from '@/components/BrandLogo.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import AiAssistantLauncher from '@/components/AiAssistantLauncher.vue'
import { useUserStore } from '@/stores/user'

const props = defineProps({
  menus: { type: Array, required: true }, // [{ path, label, icon }]
  homePath: { type: String, default: '/' },
  roleLabel: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const collapsed = ref(false)

// 取前缀最长的菜单项：进入详情页（如 /client/cases/12）时仍能高亮父级菜单
const activePath = computed(() => {
  const current = route.path
  const hit = props.menus
    .filter((m) => current === m.path || current.startsWith(`${m.path}/`))
    .sort((a, b) => b.path.length - a.path.length)[0]
  return hit?.path || current
})
const pageTitle = computed(() => route.meta.title || '')
const pageSub = computed(() => route.meta.sub || '')
const avatarText = computed(() =>
  (userStore.realName || '·').slice(0, 1),
)

async function onCommand(cmd) {
  if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出当前账号吗？', '退出登录', {
        confirmButtonText: '退出',
        cancelButtonText: '取消',
        type: 'warning',
      })
      userStore.logout()
      router.push('/login')
    } catch {
      /* 用户取消 */
    }
  }
}
</script>

<style scoped>
.app-layout {
  height: 100%;
}

/* ---------- 侧边栏 ---------- */
.aside {
  background: linear-gradient(180deg, var(--brand-navy) 0%, var(--brand-navy-deep) 100%);
  display: flex;
  flex-direction: column;
  transition: width 0.2s ease;
  overflow: hidden;
}

.brand-area {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 13px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  flex-shrink: 0;
}

.menu-scroll {
  flex: 1;
}

.menu {
  border-right: none;
  background: transparent;
  padding: 12px 8px;
  --el-menu-text-color: rgba(255, 255, 255, 0.62);
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.06);
  --el-menu-active-color: var(--brand-gold-light);
  --el-menu-item-height: 46px;
}

.menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin-bottom: 4px;
  font-size: 14px;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(201, 165, 92, 0.18), rgba(201, 165, 92, 0.04));
  font-weight: 500;
  position: relative;
}

.menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 2px;
  background: var(--brand-gold);
}

.aside-foot {
  height: 46px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 22px;
  color: rgba(255, 255, 255, 0.45);
  font-size: 13px;
  cursor: pointer;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  flex-shrink: 0;
}

.aside-foot:hover {
  color: var(--brand-gold-light);
}

/* ---------- 顶栏 ---------- */
.right {
  min-width: 0;
}

.header {
  background: #fff;
  border-bottom: 1px solid var(--brand-line);
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
}

.page-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.3;
}

.page-sub {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-chip {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 6px 10px;
  border-radius: 10px;
  cursor: pointer;
  transition: background 0.15s;
}

.user-chip:hover {
  background: var(--brand-bg);
}

.avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
  color: var(--brand-gold-light);
  font-size: 15px;
  font-weight: 600;
  display: flex;
  align-items: center;
  justify-content: center;
}

.meta .name {
  font-size: 14px;
  font-weight: 500;
  color: var(--brand-ink);
  line-height: 1.2;
}

.meta .role {
  font-size: 11px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.caret {
  color: var(--brand-muted);
  font-size: 12px;
}

.drop-head {
  padding: 10px 16px 8px;
}

.drop-name {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
}

.drop-account {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 2px;
}

/* ---------- 内容区 ---------- */
.main {
  background: var(--brand-bg);
  padding: 20px 24px;
}
</style>
