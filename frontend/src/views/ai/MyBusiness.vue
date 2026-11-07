<template>
  <div class="biz-page">
    <!-- 左：历史查询 -->
    <aside class="side-panel">
      <AiSessionList
        ref="sessionListRef"
        :active-id="sessionId"
        session-type="business"
        variant="business"
        @select="onSelect"
        @new="onNew"
        @deleted="onDeleted"
      />
    </aside>

    <!-- 右：查询主区 -->
    <section class="chat-panel">
      <header class="chat-head">
        <div class="head-left">
          <div class="head-icon">
            <el-icon :size="17"><DataLine /></el-icon>
          </div>
          <div class="head-text">
            <div class="head-title">AI督办</div>
            <div class="head-sub">
              {{
                sessionId
                  ? '正在查看历史督办记录，可继续追问'
                  : '盯案件进度、催待收款、提示快到期的事项'
              }}
            </div>
          </div>
        </div>

        <div class="head-actions">
          <el-button size="small" plain @click="goLaw">
            <el-icon><MagicStick /></el-icon>去问法律问题
          </el-button>
          <el-button size="small" @click="onNew">
            <el-icon><Plus /></el-icon>新查询
          </el-button>
        </div>
      </header>

      <div class="chat-body">
        <BusinessChatWindow
          ref="chatRef"
          :session-id="sessionId"
          @update:session-id="sessionId = $event"
          @session-created="onSessionCreated"
          @finished="onFinished"
        >
          <template #guide>
            <div class="scene-grid">
              <button
                v-for="scene in scenes"
                :key="scene.path"
                type="button"
                class="scene-card"
                @click="goScene(scene.path)"
              >
                <el-icon :size="16" class="scene-icon">
                  <component :is="scene.icon" />
                </el-icon>
                <span class="scene-name">{{ scene.label }}</span>
                <span class="scene-tip">{{ scene.desc }}</span>
              </button>
            </div>
            <p class="scene-note">
              这里只读业务台账：案子办到哪一步、还差多少钱、哪天开庭、哪份合同快到期。
              问「这种情况法律怎么规定」，请到「AI 法律问答」——两个入口的数据与口径是分开的。
            </p>
          </template>
        </BusinessChatWindow>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  Briefcase,
  Calendar,
  DataLine,
  MagicStick,
  Money,
  Plus,
  Tickets,
} from '@element-plus/icons-vue'
import BusinessChatWindow from '@/components/BusinessChatWindow.vue'
import AiSessionList from '@/components/AiSessionList.vue'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const userStore = useUserStore()

const sessionListRef = ref(null)
const chatRef = ref(null)
const sessionId = ref(null)

// 管理员与律师共用这个页面，菜单前缀不同
const basePath = computed(() => (userStore.role === 'admin' ? '/admin' : '/lawyer'))

const scenes = computed(() => [
  {
    label: '案件台账',
    desc: '状态分组 · 承办律师',
    path: `${basePath.value}/cases`,
    icon: Briefcase,
  },
  {
    label: '催收清单',
    desc: '到期未结清的期次',
    path: `${basePath.value}/billing/collect`,
    icon: Money,
  },
  {
    label: '日程',
    desc: '今日待办 · 开庭与期限',
    path: `${basePath.value}/schedule`,
    icon: Calendar,
  },
  {
    label: '合同到期',
    desc: '30 天内到期预警',
    path: `${basePath.value}/contracts`,
    icon: Tickets,
  },
])

function goScene(path) {
  if (path) router.push(path)
}

function goLaw() {
  router.push(`${basePath.value}/ai`)
}

function onSelect(id) {
  if (id === sessionId.value) return
  sessionId.value = id
}

function onNew() {
  sessionId.value = null
  chatRef.value?.newChat()
}

function onSessionCreated() {
  sessionListRef.value?.reload()
}

function onFinished() {
  sessionListRef.value?.reload()
}

function onDeleted(id) {
  if (id === sessionId.value) onNew()
}

if (route.query.session) {
  sessionId.value = Number(route.query.session) || null
}
</script>

<style scoped>
.biz-page {
  display: flex;
  gap: 16px;
  height: calc(100vh - 100px);
  min-height: 520px;
}

.side-panel {
  flex: 0 0 252px;
  min-width: 0;
}

.chat-panel {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 18px;
  border-bottom: 1px solid var(--brand-line);
  background: linear-gradient(180deg, #fff, #fcfcfd);
}

.head-left {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.head-icon {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--brand-gold-deep);
  background: linear-gradient(135deg, rgba(201, 165, 92, 0.18), rgba(29, 43, 71, 0.06));
  border: 1px solid rgba(201, 165, 92, 0.28);
}

.head-title {
  font-size: 15px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.3;
}

.head-sub {
  font-size: 12px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.head-actions {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.chat-body {
  flex: 1;
  min-height: 0;
}

/* 空态快捷入口 */
.scene-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
}

.scene-card {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 4px;
  padding: 12px 12px 11px;
  text-align: left;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  cursor: pointer;
  transition: all 0.15s;
}

.scene-card:hover {
  border-color: var(--brand-gold);
  box-shadow: 0 2px 10px rgba(29, 43, 71, 0.06);
}

.scene-icon {
  color: var(--brand-gold-deep);
}

.scene-name {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
}

.scene-tip {
  font-size: 11.5px;
  color: var(--brand-muted);
  line-height: 1.5;
}

.scene-note {
  margin: 12px 0 0;
  font-size: 12px;
  line-height: 1.7;
  color: var(--brand-muted);
}

@media (max-width: 1200px) {
  .scene-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 900px) {
  .side-panel {
    display: none;
  }
}
</style>
