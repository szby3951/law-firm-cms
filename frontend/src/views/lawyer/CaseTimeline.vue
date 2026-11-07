<template>
  <div class="case-timeline">
    <el-timeline v-if="events.length">
      <el-timeline-item
        v-for="e in events"
        :key="e.id"
        :timestamp="formatTime(e.event_date)"
        placement="top"
        :type="eventMeta[e.event_type]?.type"
        :hollow="e.event_type === 'other'"
      >
        <div class="event-item">
          <div class="event-head">
            <el-tag :type="eventMeta[e.event_type]?.type" size="small" effect="plain">
              {{ eventMeta[e.event_type]?.label || e.event_type }}
            </el-tag>
          </div>
          <div class="event-desc">{{ e.description || '—' }}</div>
        </div>
      </el-timeline-item>
    </el-timeline>
    <el-empty v-else description="暂无案件节点" :image-size="80" />
  </div>
</template>

<script setup>
const props = defineProps({
  events: { type: Array, default: () => [] },
})

const eventMeta = {
  filing: { label: '立案', type: 'primary' },
  accept: { label: '受理', type: 'info' },
  hearing: { label: '开庭', type: 'warning' },
  evidence: { label: '举证', type: 'success' },
  judgment: { label: '判决', type: 'danger' },
  other: { label: '其他', type: 'info' },
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.event-item {
  padding: 4px 0;
}

.event-head {
  margin-bottom: 6px;
}

.event-desc {
  font-size: 14px;
  color: var(--brand-text);
  line-height: 1.7;
  white-space: pre-wrap;
}
</style>
