<template>
  <div class="chat-msg" :class="{ mine }">
    <div v-if="showMeta" class="avatar" :class="mine ? 'is-mine' : 'is-peer'">
      {{ initials(senderName) }}
    </div>
    <div v-else class="avatar-holder" />

    <div class="body">
      <div v-if="showMeta" class="meta">
        <span class="name">{{ senderName }}</span>
        <span class="role" :class="message.sender_role">{{ message.sender_role_label }}</span>
        <span class="time">{{ timeText }}</span>
        <span v-if="unread && !mine" class="unread-chip">未读</span>
      </div>

      <div class="bubble" :class="{ 'is-unread': unread && !mine }">
        <div v-if="message.content" class="text">{{ message.content }}</div>

        <div v-if="message.attachments?.length" class="atts">
          <button
            v-for="att in message.attachments"
            :key="att.id"
            type="button"
            class="att"
            :title="isPreviewable(att) ? '点击预览' : '点击预览 / 下载'"
            @click="emit('preview', att)"
          >
            <span
              class="att-icon"
              :style="{ background: attachmentMeta(att).bg, color: attachmentMeta(att).color }"
            >
              <el-icon :size="14"><component :is="attachmentMeta(att).icon" /></el-icon>
            </span>
            <span class="att-info">
              <span class="att-name">{{ att.file_name }}</span>
              <span class="att-size">
                {{ attachmentMeta(att).label }} · {{ fmtFileSize(att.file_size) }}
              </span>
            </span>
          </button>
        </div>
      </div>

      <div v-if="showReadState && mine" class="foot">
        <span class="read-state" :class="{ read: message.is_read }">
          {{ message.is_read ? '对方已读' : '对方未读' }}
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { timeOf } from '@/utils/schedule'
import {
  attachmentMeta,
  fmtFileSize,
  initials,
  isPreviewable,
} from '@/utils/message'

const props = defineProps({
  message: { type: Object, required: true },
  // 是否为我发出的（右侧、深蓝气泡）
  mine: { type: Boolean, default: false },
  // 同一发送人连续发言时只在第一条显示头像与姓名
  showMeta: { type: Boolean, default: true },
  // 律师端显示「对方已读 / 未读」
  showReadState: { type: Boolean, default: false },
  // 对方发来且尚未读：气泡描边高亮 + 未读角标
  unread: { type: Boolean, default: false },
  peerName: { type: String, default: '' },
})

const emit = defineEmits(['preview'])

const senderName = computed(() => {
  if (props.mine) return props.message.sender_name || '我'
  return props.message.sender_name || props.peerName || props.message.sender_role_label
})

const timeText = computed(() => timeOf(props.message.created_at) || '')
</script>

<style scoped>
.chat-msg {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.chat-msg.mine {
  flex-direction: row-reverse;
}

.avatar,
.avatar-holder {
  width: 34px;
  height: 34px;
  border-radius: 10px;
  flex-shrink: 0;
}

.avatar {
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
}

.avatar.is-peer {
  background: linear-gradient(135deg, #f4e7c8, #e6cf9c);
  color: var(--brand-gold-deep);
  border: 1px solid #e6d4ac;
}

.avatar.is-mine {
  background: linear-gradient(135deg, var(--brand-navy-soft), var(--brand-navy-deep));
  color: var(--brand-gold-light);
}

.body {
  max-width: 72%;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.mine .body {
  align-items: flex-end;
}

.meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 5px;
  font-size: 12px;
  color: var(--brand-muted);
}

.meta .name {
  color: var(--brand-ink);
  font-weight: 600;
}

.meta .role {
  font-size: 10px;
  line-height: 15px;
  padding: 0 5px;
  border-radius: 3px;
  border: 1px solid var(--brand-line);
  color: var(--brand-muted);
}

.meta .role.client {
  color: #a5813d;
  background: #fdf8ec;
  border-color: #e6d4ac;
}

.meta .role.lawyer {
  color: #1d2b47;
  background: #eef1f7;
  border-color: #dbe1ec;
}

.meta .time {
  font-size: 11px;
  color: #b3b9c6;
}

.unread-chip {
  font-size: 10px;
  line-height: 15px;
  padding: 0 5px;
  border-radius: 3px;
  color: var(--el-color-danger);
  border: 1px solid rgba(245, 108, 108, 0.35);
}

.bubble.is-unread {
  border-color: #e6d4ac;
  background: #fffdf8;
  box-shadow: 0 1px 4px rgba(201, 165, 92, 0.14);
}

.bubble {
  padding: 10px 14px;
  border-radius: 12px;
  font-size: 14px;
  line-height: 1.75;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-top-left-radius: 4px;
  color: var(--brand-text);
  box-shadow: 0 1px 2px rgba(20, 33, 61, 0.03);
  min-width: 0;
}

.mine .bubble {
  background: linear-gradient(135deg, #24344f 0%, var(--brand-navy) 100%);
  border-color: var(--brand-navy);
  border-top-left-radius: 12px;
  border-top-right-radius: 4px;
  color: #fff;
  box-shadow: 0 2px 8px rgba(20, 33, 61, 0.16);
}

.text {
  white-space: pre-wrap;
  word-break: break-word;
}

.atts {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 8px;
}

.text + .atts {
  padding-top: 8px;
  border-top: 1px dashed rgba(20, 33, 61, 0.12);
}

.mine .text + .atts {
  border-top-color: rgba(255, 255, 255, 0.18);
}

.att {
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 320px;
  padding: 6px 9px;
  border-radius: 8px;
  border: 1px solid var(--brand-line);
  background: #f8f9fc;
  cursor: pointer;
  text-align: left;
  transition: background-color 0.18s ease, border-color 0.18s ease;
  font-family: inherit;
}

.att:hover {
  background: #fff;
  border-color: var(--brand-gold);
}

.mine .att {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.2);
  color: #fff;
}

.mine .att:hover {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.34);
}

.att-icon {
  width: 24px;
  height: 24px;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.att-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.att-name {
  font-size: 12px;
  line-height: 16px;
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.att-size {
  font-size: 11px;
  line-height: 14px;
  color: var(--brand-muted);
}

.mine .att-size {
  color: rgba(255, 255, 255, 0.62);
}

.foot {
  margin-top: 4px;
  font-size: 11px;
  color: #b3b9c6;
  padding: 0 2px;
}

.read-state.read {
  color: var(--brand-gold-deep);
}
</style>
