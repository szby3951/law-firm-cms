<template>
  <div v-if="enabled" class="ai-launcher">
    <!-- 右下角悬浮入口 -->
    <transition name="fab-pop">
      <button
        v-show="!visible"
        type="button"
        class="fab"
        title="AI 法律助手（Ctrl + /）"
        @click="store.open()"
      >
        <el-icon :size="20"><MagicStick /></el-icon>
        <span class="fab-label">AI 助手</span>
      </button>
    </transition>

    <!-- 抽屉：复用同一套聊天窗 -->
    <el-drawer
      v-model="visible"
      :size="drawerSize"
      :with-header="false"
      class="ai-drawer"
      :modal="false"
      :close-on-click-modal="true"
      append-to-body
    >
      <div class="drawer-wrap">
        <header class="drawer-head">
          <div class="head-left">
            <div class="head-icon">
              <el-icon :size="16"><MagicStick /></el-icon>
            </div>
            <div>
              <div class="head-title">AI 法律助手</div>
              <div class="head-sub">基于法律知识库作答 · 仅供参考</div>
            </div>
          </div>
          <div class="head-actions">
            <el-button link size="small" @click="onNewChat">
              <el-icon><Plus /></el-icon>新对话
            </el-button>
            <el-button link size="small" @click="goFullPage">
              完整页面<el-icon><ArrowRight /></el-icon>
            </el-button>
            <el-icon class="close-btn" @click="visible = false"><Close /></el-icon>
          </div>
        </header>

        <div class="drawer-body">
          <AiChatWindow
            ref="chatRef"
            compact
            :restricted="isClient"
            :session-id="store.sessionId"
            :prefill="store.prefill"
            :prefill-key="store.prefillKey"
            @update:session-id="store.sessionId = $event"
          />
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ArrowRight, Close, MagicStick, Plus } from '@element-plus/icons-vue'
import AiChatWindow from '@/components/AiChatWindow.vue'
import { useAiAssistantStore } from '@/stores/aiAssistant'
import { useUserStore } from '@/stores/user'
import { useBreakpoint } from '@/utils/useBreakpoint'

const store = useAiAssistantStore()
const userStore = useUserStore()
const route = useRoute()
const router = useRouter()
const chatRef = ref(null)

const windowWidth = ref(window.innerWidth)
const isClient = computed(() => userStore.role === 'client')

// 已经在 AI 页或「AI督办」页时不显示悬浮窗：前者会撞出两个输入框，
// 后者会让用户在同一个屏幕上同时看到法律问答与业务查询，容易搞混在问什么。
const onAiPage = computed(() =>
  ['LawyerAi', 'AdminAi', 'ClientAi', 'LawyerBusiness', 'AdminBusiness', 'ClientBusiness'].includes(
    route.name,
  ),
)

// 手机上的留言页底部有输入框和发送按钮，悬浮球正好压在上面；
// 而对话场景本来也不适合再叠一个 AI 窗，窄屏时直接不显示。
const { isMobile } = useBreakpoint()
const conflictWithMobileComposer = computed(
  () => isMobile.value && /(^|\/)(messages)$/.test(route.path),
)

const enabled = computed(
  () =>
    userStore.isLoggedIn &&
    !route.meta.public &&
    !onAiPage.value &&
    !conflictWithMobileComposer.value,
)

const drawerSize = computed(() => (windowWidth.value < 720 ? '100%' : '480px'))

const visible = computed({
  get: () => store.visible,
  set: (val) => {
    if (val) store.visible = true
    else store.close()
  },
})

function goFullPage() {
  const path = isClient.value ? '/client/ai' : userStore.role === 'admin' ? '/admin/ai' : '/lawyer/ai'
  visible.value = false
  router.push(path)
}

function onNewChat() {
  store.reset()
  chatRef.value?.newChat()
}

// Ctrl/Cmd + / 快速唤起，与「随手问一句」的使用场景匹配
function onKeydown(event) {
  if ((event.ctrlKey || event.metaKey) && event.key === '/') {
    event.preventDefault()
    if (enabled.value) store.toggle()
  }
}

function onResize() {
  windowWidth.value = window.innerWidth
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown)
  window.addEventListener('resize', onResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  window.removeEventListener('resize', onResize)
})
</script>

<style scoped>
/* 浮层不参与父级 flex 布局，否则会在 el-container 里撑出一个空列 */
.ai-launcher {
  display: contents;
}

.fab {
  position: fixed;
  right: 26px;
  bottom: 30px;
  z-index: 2100;
  display: flex;
  align-items: center;
  gap: 0;
  height: 52px;
  width: 52px;
  padding: 0;
  border: 1px solid rgba(201, 165, 92, 0.55);
  border-radius: 26px;
  color: var(--brand-gold-light);
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
  box-shadow: 0 8px 24px rgba(13, 23, 48, 0.28);
  cursor: pointer;
  overflow: hidden;
  justify-content: center;
  transition: width 0.22s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.fab:hover {
  width: 118px;
  box-shadow: 0 10px 28px rgba(13, 23, 48, 0.36);
  transform: translateY(-1px);
}

.fab-label {
  max-width: 0;
  opacity: 0;
  white-space: nowrap;
  font-size: 13px;
  margin-left: 0;
  transition: all 0.22s ease;
}

.fab:hover .fab-label {
  max-width: 70px;
  opacity: 1;
  margin-left: 8px;
}

.fab-pop-enter-active,
.fab-pop-leave-active {
  transition: opacity 0.2s ease, transform 0.2s ease;
}

.fab-pop-enter-from,
.fab-pop-leave-to {
  opacity: 0;
  transform: scale(0.85);
}

.drawer-wrap {
  display: flex;
  flex-direction: column;
  height: 100%;
}

.drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 14px 16px;
  border-bottom: 1px solid var(--brand-line);
  background: linear-gradient(180deg, #fff, #fcfcfd);
}

.head-left {
  display: flex;
  align-items: center;
  gap: 9px;
  min-width: 0;
}

.head-icon {
  width: 30px;
  height: 30px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-gold-deep);
  background: linear-gradient(135deg, rgba(201, 165, 92, 0.18), rgba(29, 43, 71, 0.06));
  border: 1px solid rgba(201, 165, 92, 0.28);
}

.head-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.3;
}

.head-sub {
  font-size: 11px;
  color: var(--brand-muted);
  margin-top: 1px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.close-btn {
  margin-left: 4px;
  color: var(--brand-muted);
  cursor: pointer;
  font-size: 15px;
}

.close-btn:hover {
  color: var(--brand-ink);
}

.drawer-body {
  flex: 1;
  min-height: 0;
}
</style>

<style>
/* el-drawer 的内边距要清掉，聊天窗自己管留白 */
.ai-drawer .el-drawer__body {
  padding: 0;
  overflow: hidden;
}

.ai-drawer {
  box-shadow: -8px 0 28px rgba(13, 23, 48, 0.12);
}

/* ---------- 手机端：悬浮球缩小并贴边，展开态交给抽屉（已按 100% 宽处理） ---------- */
@media (max-width: 768px) {
  .fab {
    right: 14px;
    bottom: calc(16px + env(safe-area-inset-bottom, 0px));
    height: 46px;
    width: 46px;
    border-radius: 23px;
  }

  .fab:hover {
    width: 46px;
    transform: none;
  }
}
</style>
