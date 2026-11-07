<template>
  <div
    class="composer"
    :class="{ dragging, disabled }"
    @dragover.prevent="dragging = true"
    @dragleave.prevent="dragging = false"
    @drop.prevent="onDrop"
  >
    <div v-if="files.length" class="pending">
      <div v-for="f in files" :key="f.uid" class="pending-item">
        <span
          class="p-icon"
          :style="{ background: fileMeta(f).bg, color: fileMeta(f).color }"
        >
          <el-icon :size="13"><component :is="fileMeta(f).icon" /></el-icon>
        </span>
        <span class="p-name">{{ f.name }}</span>
        <span class="p-size">{{ fmtFileSize(f.size) }}</span>
        <el-icon class="p-remove" @click="removeFile(f.uid)"><Close /></el-icon>
      </div>
    </div>

    <el-input
      ref="inputRef"
      v-model="content"
      type="textarea"
      :autosize="{ minRows: 2, maxRows: 5 }"
      :maxlength="2000"
      show-word-limit
      resize="none"
      :disabled="disabled"
      :placeholder="placeholder"
      class="composer-input"
      @keydown.ctrl.enter.prevent="submit"
      @keydown.meta.enter.prevent="submit"
    />

    <div class="toolbar">
      <div class="tool-left">
        <el-button text :disabled="disabled" @click="pick">
          <el-icon><Paperclip /></el-icon>附件
        </el-button>
        <span class="hint">图片 / PDF / Office 文档，单个 ≤ 20MB，最多 {{ MAX_ATTACHMENT_COUNT }} 个</span>
      </div>
      <div class="tool-right">
        <span class="kbd">Ctrl / ⌘ + Enter 发送</span>
        <el-button type="primary" :loading="loading" :disabled="!canSend" @click="submit">
          <el-icon><Promotion /></el-icon>发送
        </el-button>
      </div>
    </div>

    <div v-if="dragging" class="drop-mask">松开鼠标即可添加附件</div>

    <input
      ref="fileRef"
      type="file"
      multiple
      :accept="ATTACHMENT_ACCEPT"
      class="hidden-input"
      @change="onPick"
    />
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Close, Paperclip, Promotion } from '@element-plus/icons-vue'
import {
  ATTACHMENT_ACCEPT,
  MAX_ATTACHMENT_COUNT,
  MAX_ATTACHMENT_SIZE,
  attachmentMeta,
  fmtFileSize,
} from '@/utils/message'

const props = defineProps({
  loading: { type: Boolean, default: false },
  disabled: { type: Boolean, default: false },
  placeholder: { type: String, default: '输入留言内容…' },
})

const emit = defineEmits(['send'])

const content = ref('')
const files = ref([])
const dragging = ref(false)
const fileRef = ref(null)
const inputRef = ref(null)

const canSend = computed(
  () =>
    !props.loading &&
    !props.disabled &&
    (!!content.value.trim() || files.value.length > 0),
)

function fileMeta(f) {
  return attachmentMeta({ file_name: f.name, mime_type: f.type })
}

function pick() {
  if (props.disabled) return
  fileRef.value?.click()
}

function addFiles(list) {
  for (const file of list) {
    if (files.value.length >= MAX_ATTACHMENT_COUNT) {
      ElMessage.warning(`一次最多添加 ${MAX_ATTACHMENT_COUNT} 个附件`)
      break
    }
    if (file.size > MAX_ATTACHMENT_SIZE) {
      ElMessage.warning(`${file.name} 超过 20MB，已跳过`)
      continue
    }
    if (file.size === 0) {
      ElMessage.warning(`${file.name} 是空文件，已跳过`)
      continue
    }
    const dup = files.value.some(
      (f) => f.name === file.name && f.size === file.size,
    )
    if (dup) continue
    files.value.push({
      uid: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: file.name,
      size: file.size,
      type: file.type,
      file,
    })
  }
}

function onPick(event) {
  const picked = Array.from(event.target.files || [])
  event.target.value = ''
  addFiles(picked)
}

function onDrop(event) {
  dragging.value = false
  if (props.disabled) return
  const dropped = Array.from(event.dataTransfer?.files || [])
  if (dropped.length) addFiles(dropped)
}

function removeFile(uid) {
  files.value = files.value.filter((f) => f.uid !== uid)
}

function submit() {
  if (!canSend.value) return
  emit('send', {
    content: content.value.trim(),
    files: files.value.slice(),
  })
}

function reset() {
  content.value = ''
  files.value = []
}

function focus() {
  inputRef.value?.focus?.()
}

defineExpose({ reset, focus })
</script>

<style scoped>
.composer {
  position: relative;
  border-top: 1px solid var(--brand-line);
  background: #fff;
  padding: 12px 16px 10px;
  flex-shrink: 0;
}

.composer.dragging {
  background: #fdfbf6;
  box-shadow: inset 0 0 0 1px var(--brand-gold);
}

.pending {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}

.pending-item {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  border: 1px solid var(--brand-line);
  background: #f8f9fc;
  border-radius: 8px;
  max-width: 300px;
}

.p-icon {
  width: 22px;
  height: 22px;
  border-radius: 5px;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.p-name {
  font-size: 12px;
  color: var(--brand-text);
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.p-size {
  font-size: 11px;
  color: var(--brand-muted);
}

.p-remove {
  color: var(--brand-muted);
  cursor: pointer;
  font-size: 12px;
}

.p-remove:hover {
  color: var(--el-color-danger);
}

.composer-input :deep(.el-textarea__inner) {
  border-radius: 8px;
  border-color: var(--brand-line);
  background: #fcfcfe;
  font-size: 14px;
  line-height: 1.7;
  padding: 8px 12px 22px;
  box-shadow: none;
}

.composer-input :deep(.el-textarea__inner:focus) {
  border-color: var(--brand-gold);
  background: #fff;
}

.composer-input :deep(.el-input__count) {
  right: 10px;
  bottom: 2px;
  font-size: 11px;
  background: transparent;
  color: #b3b9c6;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.tool-left,
.tool-right {
  display: flex;
  align-items: center;
  gap: 10px;
}

.tool-left :deep(.el-button) {
  padding: 4px 6px;
  color: var(--brand-navy);
  font-size: 13px;
}

.hint,
.kbd {
  font-size: 11px;
  color: var(--brand-muted);
}

.kbd {
  color: #b3b9c6;
}

.drop-mask {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 13px;
  color: var(--brand-gold-deep);
  background: rgba(253, 251, 246, 0.92);
  border: 1px dashed var(--brand-gold);
  border-radius: 8px;
  pointer-events: none;
}

.hidden-input {
  display: none;
}

@media (max-width: 900px) {
  .hint,
  .kbd {
    display: none;
  }
}
</style>
