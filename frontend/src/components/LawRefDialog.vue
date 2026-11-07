<template>
  <el-dialog
    :model-value="modelValue"
    width="680px"
    top="8vh"
    class="ref-dialog"
    destroy-on-close
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="ref-head">
        <div class="ref-badge">
          {{ refData?.source === 'law' ? '法条' : '律所知识' }}
        </div>
        <div class="ref-title-wrap">
          <div class="ref-title">{{ refData?.label || '引用' }}</div>
          <div v-if="metaLine" class="ref-sub">{{ metaLine }}</div>
        </div>
        <div v-if="refData?.index" class="ref-index">[{{ refData.index }}]</div>
      </div>
    </template>

    <div v-if="refData" class="ref-body">
      <div v-if="paragraphs.length" class="ref-content">
        <p v-for="(p, i) in paragraphs" :key="i">{{ p }}</p>
      </div>
      <el-empty v-else description="该引用没有可展示的正文" :image-size="70" />

      <div class="ref-foot">
        <span class="score">检索相关度 {{ (refData.score ?? 0).toFixed(2) }}</span>
        <el-button link type="primary" @click="copyRef">
          <el-icon><CopyDocument /></el-icon>复制条文
        </el-button>
      </div>

      <p class="ref-tip">
        条文来自律所本地知识库快照，引用前请核对现行有效版本；已被修订的条文会在上方标注效力状态。
      </p>
    </div>
  </el-dialog>
</template>

<script setup>
import { computed } from 'vue'
import { ElMessage } from 'element-plus'
import { CopyDocument } from '@element-plus/icons-vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  refData: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue'])

const metaLine = computed(() => {
  const r = props.refData
  if (!r) return ''
  const parts = []
  if (r.source === 'law') {
    if (r.chapter) parts.push(r.chapter)
    if (r.effective_status) parts.push(r.effective_status)
  } else if (r.category) {
    parts.push(r.category)
  }
  return parts.join(' · ')
})

// 条文正文按空行/换行拆段，保留「一、二、」这类分项的行距
const paragraphs = computed(() => {
  const text = String(props.refData?.content || '').trim()
  if (!text) return []
  return text
    .split(/\n+/)
    .map((p) => p.trim())
    .filter(Boolean)
})

async function copyRef() {
  const r = props.refData
  if (!r) return
  const text = `${r.label || ''}\n${r.content || ''}`.trim()
  try {
    await navigator.clipboard.writeText(text)
    ElMessage.success('条文已复制')
  } catch {
    ElMessage.warning('复制失败，请手动选择文本')
  }
}
</script>

<style scoped>
.ref-head {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.ref-badge {
  flex-shrink: 0;
  padding: 3px 9px;
  border-radius: 6px;
  font-size: 12px;
  color: var(--brand-gold-deep);
  background: rgba(201, 165, 92, 0.14);
  border: 1px solid rgba(201, 165, 92, 0.28);
}

.ref-title-wrap {
  flex: 1;
  min-width: 0;
}

.ref-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--brand-ink);
  line-height: 1.4;
}

.ref-sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--brand-muted);
}

.ref-index {
  font-size: 13px;
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

.ref-body {
  margin-top: -6px;
}

.ref-content {
  max-height: 52vh;
  overflow-y: auto;
  padding: 16px 18px;
  border-radius: 10px;
  background: #fcfcfd;
  border: 1px solid var(--brand-line);
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
  font-size: 15px;
  line-height: 2;
  color: var(--brand-text);
}

.ref-content p {
  margin: 0 0 8px;
  text-indent: 2em;
}

.ref-content p:last-child {
  margin-bottom: 0;
}

.ref-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}

.ref-foot .score {
  font-size: 12px;
  color: var(--brand-muted);
}

.ref-tip {
  margin: 4px 0 0;
  font-size: 12px;
  line-height: 1.6;
  color: var(--brand-muted);
}
</style>
