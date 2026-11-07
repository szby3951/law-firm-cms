<template>
  <div class="ai-page">
    <!-- 左：历史会话 -->
    <aside class="side-panel">
      <AiSessionList
        ref="sessionListRef"
        :active-id="sessionId"
        session-type="chat"
        @select="onSelect"
        @new="onNew"
        @deleted="onDeleted"
      />
    </aside>

    <!-- 右：问答主区 -->
    <section class="chat-panel">
      <header class="chat-head">
        <div class="head-left">
          <div class="head-icon">
            <el-icon :size="17"><MagicStick /></el-icon>
          </div>
          <div class="head-text">
            <div class="head-title">AI 法律助手</div>
            <div class="head-sub">
              {{
                sessionId
                  ? '正在查看历史会话，可继续追问'
                  : '查法条、查办案流程，每次结论都标注引用条文'
              }}
            </div>
          </div>
        </div>

        <div class="head-actions">
          <el-button size="small" plain @click="goBusiness">
            <el-icon><DataLine /></el-icon>AI 督办
          </el-button>
          <el-dropdown trigger="click" @command="goScene">
            <el-button size="small" plain>
              <el-icon><Grid /></el-icon>场景直达
              <el-icon class="caret"><ArrowDown /></el-icon>
            </el-button>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item
                  v-for="scene in scenes"
                  :key="scene.path"
                  :command="scene.path"
                >
                  <el-icon><component :is="scene.icon" /></el-icon>
                  <span class="scene-label">{{ scene.label }}</span>
                  <span class="scene-desc">{{ scene.desc }}</span>
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>

          <el-button size="small" @click="onNew">
            <el-icon><Plus /></el-icon>新对话
          </el-button>
        </div>
      </header>

      <div class="chat-body">
        <AiChatWindow
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
              这里只答法律问题：法条怎么规定、程序怎么走、这类情形一般怎么处理。
              要盯自己案子的进度、待收款与到期节点，请用顶部的「AI 督办」——那边读的是
              业务台账，不引法条，回答里也不会有引用编号。
            </p>
          </template>
        </AiChatWindow>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  ArrowDown,
  Briefcase,
  DataLine,
  Grid,
  MagicStick,
  Plus,
  Tickets,
  User,
  EditPen,
} from '@element-plus/icons-vue'
import AiChatWindow from '@/components/AiChatWindow.vue'
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
    label: '智能文书',
    desc: '起诉状 / 答辩状等 7 类初稿',
    path: `${basePath.value}/documents`,
    icon: EditPen,
  },
  {
    label: '合同审查',
    desc: '上传合同生成风险清单',
    path: `${basePath.value}/contracts`,
    icon: Tickets,
  },
  {
    label: '案件摘要',
    desc: '案卷一键归纳六节要点',
    path: `${basePath.value}/cases`,
    icon: Briefcase,
  },
  {
    label: '客户画像',
    desc: '诉求 / 风险 / 跟进建议',
    path: `${basePath.value}/clients`,
    icon: User,
  },
])

function goScene(path) {
  if (path) router.push(path)
}

function goBusiness() {
  router.push(`${basePath.value}/business`)
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

// 从「历史会话」进入时保留滚动位置即可，无需额外初始化
if (route.query.session) {
  sessionId.value = Number(route.query.session) || null
}
</script>

<style scoped>
.ai-page {
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

.caret {
  margin-left: 2px;
  font-size: 11px;
}

.chat-body {
  flex: 1;
  min-height: 0;
}

/* 空态里的场景直达 */
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

.scene-label {
  margin: 0 8px 0 2px;
}

.scene-desc {
  font-size: 11.5px;
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
