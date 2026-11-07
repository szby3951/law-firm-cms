<template>
  <div class="client-ai">
    <!-- 欢迎区：与客户端其他页面保持同一版式 -->
    <div class="welcome-card">
      <div class="welcome-text">
        <h2>AI 法律问答</h2>
        <p>用日常语言说清你遇到的事，AI 会解释法律怎么规定、下一步该准备什么</p>
      </div>
      <div class="welcome-badge">智能咨询</div>
    </div>

    <!-- 合规提示（9.9.1 的客户端落点） -->
    <div class="notice-bar">
      <el-icon :size="14"><InfoFilled /></el-icon>
      <span>
        AI 回答基于法律法规与律所知识库生成，仅供参考，不构成法律意见，也不能替代律师对具体案件的专业判断。
      </span>
      <el-button link type="primary" class="notice-btn" @click="$router.push('/client/business')">
        去 AI 督办<el-icon><ArrowRight /></el-icon>
      </el-button>
    </div>

    <!-- 问答区 -->
    <section class="chat-panel">
      <header class="chat-head">
        <div class="head-left">
          <div class="head-icon">
            <el-icon :size="17"><MagicStick /></el-icon>
          </div>
          <div class="head-text">
            <div class="head-title">法律咨询</div>
            <div class="head-sub">
              {{ sessionId ? '历史对话 · 可继续追问' : '新对话 · 描述越具体，回答越有针对性' }}
            </div>
          </div>
        </div>

        <div class="head-actions">
          <el-popover
            ref="historyPopRef"
            placement="bottom-end"
            :width="280"
            trigger="click"
            @show="historyRef?.reload()"
          >
            <template #reference>
              <el-button size="small" plain>
                <el-icon><Clock /></el-icon>历史对话
              </el-button>
            </template>

            <SessionHistoryPop
              ref="historyRef"
              title="最近咨询"
              empty-text="还没有历史对话"
              session-type="chat"
              :active-id="sessionId"
              @select="openSession"
            />
          </el-popover>

          <el-button size="small" @click="onNew">
            <el-icon><Plus /></el-icon>新对话
          </el-button>
        </div>
      </header>

      <div class="chat-body">
        <AiChatWindow
          ref="chatRef"
          restricted
          :session-id="sessionId"
          :placeholder="'描述你的情况，例如：去年借给朋友 5 万元，有转账记录和聊天记录，现在对方不接电话…'"
          @update:session-id="sessionId = $event"
          @session-created="onSessionCreated"
        />
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { ArrowRight, Clock, InfoFilled, MagicStick, Plus } from '@element-plus/icons-vue'
import AiChatWindow from '@/components/AiChatWindow.vue'
import SessionHistoryPop from '@/components/SessionHistoryPop.vue'

const chatRef = ref(null)
const sessionId = ref(null)

const historyRef = ref(null)
const historyPopRef = ref(null)

function openSession(id) {
  historyPopRef.value?.hide()
  // 列表里删掉当前会话时会传 null：一并清空正文，避免输入框挂着已删除的 id
  if (id == null) {
    sessionId.value = null
    chatRef.value?.newChat()
    return
  }
  sessionId.value = id
}

function onNew() {
  sessionId.value = null
  chatRef.value?.newChat()
}

function onSessionCreated() {
  // 新会话已建好，顺手刷新历史列表，下次点开就在里面
  historyRef.value?.reload()
}
</script>

<style scoped>
.client-ai {
  display: flex;
  flex-direction: column;
  gap: 12px;
  height: calc(100vh - 100px);
  min-height: 560px;
}

/* ---------- 欢迎卡：与「我的案件」一致 ---------- */
.welcome-card {
  flex-shrink: 0;
  background: linear-gradient(135deg, var(--brand-navy-soft) 0%, var(--brand-navy) 60%, var(--brand-navy-deep) 100%);
  border-radius: 12px;
  padding: 22px 28px;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.welcome-text h2 {
  margin: 0 0 6px;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 1px;
}

.welcome-text p {
  margin: 0;
  font-size: 13px;
  color: rgba(255, 255, 255, 0.55);
}

.welcome-badge {
  padding: 5px 14px;
  border: 1px solid rgba(201, 165, 92, 0.5);
  border-radius: 20px;
  color: var(--brand-gold-light);
  font-size: 12px;
  letter-spacing: 2px;
}

/* ---------- 合规提示 ---------- */
.notice-bar {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 9px 14px;
  border-radius: 10px;
  background: rgba(201, 165, 92, 0.08);
  border: 1px solid rgba(201, 165, 92, 0.28);
  font-size: 12.5px;
  line-height: 1.6;
  color: #8a6a24;
}

.notice-btn {
  flex-shrink: 0;
  margin-left: auto;
  font-size: 12.5px;
}

/* ---------- 问答区 ---------- */
.chat-panel {
  flex: 1;
  min-height: 0;
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

@media (max-width: 900px) {
  .client-ai {
    height: auto;
    min-height: 0;
  }

  .notice-bar {
    flex-wrap: wrap;
  }
}
</style>
