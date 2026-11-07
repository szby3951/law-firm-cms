<template>
  <el-dialog
    :model-value="modelValue"
    :title="attachment?.file_name || '附件预览'"
    width="880px"
    top="6vh"
    class="att-viewer"
    @update:model-value="(v) => emit('update:modelValue', v)"
    @closed="cleanup"
  >
    <div v-loading="loading" class="viewer-body">
      <img v-if="kind === 'image' && objectUrl" :src="objectUrl" alt="" class="viewer-img" />
      <iframe v-else-if="kind === 'pdf' && objectUrl" :src="objectUrl" class="viewer-pdf" />
      <div v-else-if="!loading" class="fallback">
        <div class="fallback-icon" :style="{ background: meta.bg, color: meta.color }">
          <el-icon :size="26"><component :is="meta.icon" /></el-icon>
        </div>
        <div class="fallback-name">{{ attachment?.file_name }}</div>
        <div class="fallback-tip">
          {{ canPreview ? '附件加载中，请稍候…' : '该类型暂不支持在线预览，可下载后查看' }}
        </div>
      </div>
    </div>

    <template #footer>
      <span class="foot-meta">
        {{ meta.label }} · {{ fmtFileSize(attachment?.file_size) }}
      </span>
      <el-button @click="emit('update:modelValue', false)">关闭</el-button>
      <el-button type="primary" :loading="downloading" @click="download">下载</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { downloadAttachment, fetchAttachmentBlob } from '@/api/messages'
import { attachmentMeta, fmtFileSize, isPreviewable } from '@/utils/message'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  attachment: { type: Object, default: null },
})

const emit = defineEmits(['update:modelValue'])

const loading = ref(false)
const downloading = ref(false)
const objectUrl = ref('')
let seq = 0

const meta = computed(() => attachmentMeta(props.attachment))
const kind = computed(() => meta.value.kind)
const canPreview = computed(() => !!props.attachment && isPreviewable(props.attachment))

function cleanup() {
  seq += 1
  if (objectUrl.value) {
    URL.revokeObjectURL(objectUrl.value)
    objectUrl.value = ''
  }
  loading.value = false
}

async function load() {
  cleanup()
  if (!props.modelValue || !canPreview.value) return
  const my = ++seq
  loading.value = true
  try {
    const res = await fetchAttachmentBlob(props.attachment.id)
    if (my !== seq) return
    const blob =
      res.data instanceof Blob
        ? res.data
        : new Blob([res.data], { type: props.attachment.mime_type || '' })
    objectUrl.value = URL.createObjectURL(blob)
  } catch {
    // 拦截器已提示，界面走「暂不支持预览」兜底
  } finally {
    if (my === seq) loading.value = false
  }
}

async function download() {
  if (!props.attachment) return
  downloading.value = true
  try {
    const name = await downloadAttachment(props.attachment)
    ElMessage.success(`已下载 ${name}`)
  } finally {
    downloading.value = false
  }
}

watch(
  () => [props.modelValue, props.attachment?.id],
  () => load(),
  { immediate: true },
)

onBeforeUnmount(cleanup)
</script>

<style scoped>
.viewer-body {
  min-height: 320px;
  max-height: 70vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f7f8fb;
  border-radius: 8px;
  overflow: auto;
}

.viewer-img {
  max-width: 100%;
  max-height: 68vh;
  object-fit: contain;
  display: block;
}

.viewer-pdf {
  width: 100%;
  height: 68vh;
  border: 0;
  background: #fff;
}

.fallback {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 10px;
  padding: 52px 20px;
  color: var(--brand-muted);
}

.fallback-icon {
  width: 54px;
  height: 54px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
}

.fallback-name {
  font-size: 14px;
  color: var(--brand-ink);
  font-weight: 600;
}

.fallback-tip {
  font-size: 12px;
  color: var(--brand-muted);
}

.att-viewer :deep(.el-dialog__footer) {
  display: flex;
  align-items: center;
  gap: 8px;
}

.foot-meta {
  margin-right: auto;
  font-size: 12px;
  color: var(--brand-muted);
}
</style>
