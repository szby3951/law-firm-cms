<template>
  <div class="stat-cards" :class="`cols-${columns}`" v-loading="loading">
    <div
      v-for="item in items"
      :key="item.label"
      class="stat-card"
      :style="{ '--tone': toneOf(item.tone).color, '--tone-soft': toneOf(item.tone).soft }"
    >
      <div class="stat-head">
        <span class="stat-label">{{ item.label }}</span>
        <span v-if="item.icon" class="stat-icon">
          <el-icon :size="14"><component :is="item.icon" /></el-icon>
        </span>
      </div>

      <div class="stat-value">
        <span class="num">{{ item.value }}</span>
        <span v-if="item.unit" class="unit">{{ item.unit }}</span>
      </div>

      <div v-if="item.hint" class="stat-hint">{{ item.hint }}</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  // [{ label, value, unit, icon, tone, hint }]
  items: { type: Array, required: true },
  columns: { type: Number, default: 4 },
  loading: { type: Boolean, default: false },
})

const TONES = {
  navy: { color: '#14213d', soft: '#eef1f7' },
  gold: { color: '#a5813d', soft: '#faf3e7' },
  green: { color: '#1D9E75', soft: '#eaf5ef' },
  rose: { color: '#993556', soft: '#faeef0' },
  slate: { color: '#59637a', soft: '#f0f2f6' },
}

function toneOf(tone) {
  return TONES[tone] || TONES.navy
}
</script>

<style scoped>
.stat-cards {
  display: grid;
  gap: 14px;
}

.cols-3 {
  grid-template-columns: repeat(3, 1fr);
}

.cols-4 {
  grid-template-columns: repeat(4, 1fr);
}

.cols-5 {
  grid-template-columns: repeat(5, 1fr);
}

.cols-6 {
  grid-template-columns: repeat(6, 1fr);
}

.stat-card {
  position: relative;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  padding: 16px 18px 15px;
  overflow: hidden;
  transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease;
}

/* 顶部渐变细线：用品牌色系做轻度标识，避免大色块 */
.stat-card::before {
  content: '';
  position: absolute;
  inset: 0 0 auto 0;
  height: 2px;
  background: linear-gradient(90deg, var(--tone) 0%, transparent 92%);
  opacity: 0.75;
}

.stat-card:hover {
  transform: translateY(-2px);
  border-color: #dde1ea;
  box-shadow: 0 8px 22px rgba(20, 33, 61, 0.06);
}

.stat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.stat-label {
  font-size: 12px;
  color: var(--brand-muted);
  letter-spacing: 0.3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.stat-icon {
  width: 24px;
  height: 24px;
  border-radius: 7px;
  background: var(--tone-soft);
  color: var(--tone);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.stat-value {
  display: flex;
  align-items: baseline;
  gap: 3px;
  margin-top: 10px;
}

.num {
  font-size: 26px;
  font-weight: 600;
  line-height: 1.1;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.4px;
}

.unit {
  font-size: 12px;
  color: var(--brand-muted);
}

.stat-hint {
  margin-top: 6px;
  font-size: 11px;
  color: var(--brand-muted);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

@media (max-width: 1320px) {
  .cols-6 {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 1080px) {
  .cols-3,
  .cols-4,
  .cols-5,
  .cols-6 {
    grid-template-columns: repeat(2, 1fr);
  }
}

/* 手机：两列，缩小数值字号，长金额（¥12,345.67）才不会被截断 */
@media (max-width: 768px) {
  .stat-value {
    margin-top: 8px;
  }

  .num {
    font-size: 20px;
    letter-spacing: -0.2px;
  }

  .unit {
    font-size: 11px;
  }

  .stat-hint {
    font-size: 10px;
  }
}
</style>
