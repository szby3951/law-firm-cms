<template>
  <el-container class="app-layout">
    <!-- ============ 桌面/平板：常驻侧边栏 ============ -->
    <el-aside v-if="!isMobile" :width="navCollapsed ? '64px' : '220px'" class="aside">
      <SideNav
        :menus="menus"
        :active-path="activePath"
        :home-path="homePath"
        :collapsed="navCollapsed"
        show-collapse
        @toggle="collapsed = !collapsed"
      />
    </el-aside>

    <!-- ============ 手机：侧边栏收进抽屉，由顶栏汉堡唤起 ============ -->
    <el-drawer
      v-model="drawerOpen"
      class="nav-drawer"
      direction="ltr"
      size="252px"
      :with-header="false"
      :show-close="false"
    >
      <SideNav
        :menus="menus"
        :active-path="activePath"
        :home-path="homePath"
        @select="drawerOpen = false"
      />
    </el-drawer>

    <!-- ============ 右侧：顶栏 + 内容 ============ -->
    <el-container class="right">
      <el-header class="header" :height="isMobile ? '52px' : '60px'">
        <div class="header-left">
          <button
            v-if="isMobile"
            type="button"
            class="nav-toggle"
            aria-label="打开导航菜单"
            @click="drawerOpen = true"
          >
            <el-icon :size="20"><Menu /></el-icon>
          </button>

          <div class="head-text">
            <div class="page-title">{{ pageTitle }}</div>
            <div v-if="!isMobile" class="page-sub">{{ pageSub }}</div>
          </div>
        </div>

        <div class="header-right">
          <NotificationBell />

          <el-dropdown trigger="click" @command="onCommand">
            <div class="user-chip">
              <div class="avatar">{{ avatarText }}</div>
              <div v-if="!isMobile" class="meta">
                <div class="name">{{ userStore.realName }}</div>
                <div class="role">{{ roleLabel }}</div>
              </div>
              <el-icon v-if="!isMobile" class="caret"><ArrowDown /></el-icon>
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
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import SideNav from '@/components/SideNav.vue'
import NotificationBell from '@/components/NotificationBell.vue'
import AiAssistantLauncher from '@/components/AiAssistantLauncher.vue'
import { useUserStore } from '@/stores/user'
import { useBreakpoint } from '@/utils/useBreakpoint'

const props = defineProps({
  menus: { type: Array, required: true }, // [{ path, label, icon }]
  homePath: { type: String, default: '/' },
  roleLabel: { type: String, default: '' },
})

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()
const { isMobile, isTablet } = useBreakpoint()

// 桌面端手动折叠；平板（769–1024）自动折叠为图标条，给内容让宽度
const collapsed = ref(false)
const navCollapsed = computed(() => collapsed.value || isTablet.value)

// 手机抽屉：跳转后自动收起，避免遮住内容
const drawerOpen = ref(false)
watch(() => route.path, () => {
  drawerOpen.value = false
})

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

/* ---------- 侧边栏容器（内容样式在 SideNav 内） ---------- */
.aside {
  overflow: hidden;
  transition: width 0.2s ease;
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

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.head-text {
  min-width: 0;
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

.nav-toggle {
  width: 36px;
  height: 36px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  border: none;
  border-radius: 9px;
  background: transparent;
  color: var(--brand-ink);
  cursor: pointer;
  padding: 0;
  -webkit-tap-highlight-color: transparent;
}

.nav-toggle:active {
  background: var(--brand-bg);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
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

/* ---------- 手机端收边距 ---------- */
@media (max-width: 768px) {
  .header {
    padding: 0 10px 0 6px;
  }

  .page-title {
    font-size: 15px;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .user-chip {
    padding: 4px;
  }

  .avatar {
    width: 32px;
    height: 32px;
    font-size: 14px;
  }

  .main {
    /* 底部留白：避免 AI 悬浮球压住页面最后一个元素 */
    padding: 12px 12px 72px;
  }
}
</style>
