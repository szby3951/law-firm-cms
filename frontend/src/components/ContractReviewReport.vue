<template>
  <div class="review-report">
    <!-- 概览 -->
    <div class="report-head">
      <div class="level-pill" :class="levelClass">
        <span class="dot" />
        <span>{{ report.level_label || '无' }}风险</span>
      </div>
      <div class="counts">
        <span class="chip high">高 {{ counts.high }}</span>
        <span class="chip mid">中 {{ counts.mid }}</span>
        <span class="chip low">低 {{ counts.low }}</span>
        <span class="chip total">共 {{ counts.total }} 条</span>
      </div>
      <div class="spacer" />
      <span class="meta">
        <template v-if="report.model">{{ report.model }}</template>
        <template v-if="report.reviewed_at"> · {{ formatTime(report.reviewed_at) }}</template>
      </span>
    </div>

    <p v-if="report.summary" class="summary">{{ report.summary }}</p>

    <!-- 缺失条款 / 空白项 -->
    <div v-if="missing.length || placeholderCount" class="alerts">
      <div v-if="missing.length" class="alert-line">
        <el-icon><WarningFilled /></el-icon>
        <span class="alert-label">合同中未见：</span>
        <el-tag v-for="item in missing" :key="item" size="small" type="warning" effect="plain">
          {{ item }}
        </el-tag>
      </div>
      <div v-if="placeholderCount" class="alert-line">
        <el-icon><EditPen /></el-icon>
        <span class="alert-label">未填写的空白：</span>
        <span class="alert-text">{{ placeholderCount }} 处</span>
        <span v-if="placeholderSamples.length" class="alert-samples">
          （如 {{ placeholderSamples.join('；') }}）
        </span>
      </div>
    </div>

    <!-- 筛选 -->
    <div class="toolbar">
      <div class="filters">
        <button
          v-for="tab in tabs"
          :key="tab.value"
          class="filter"
          :class="{ active: level === tab.value }"
          @click="level = tab.value"
        >
          {{ tab.label }}
        </button>
      </div>
      <span class="hint">「待核对」表示模型摘录的原文未能与合同逐字匹配，请人工确认</span>
    </div>

    <!-- 风险列表 -->
    <div class="risk-list">
      <div v-for="risk in filteredRisks" :key="risk.id" class="risk-item" :class="risk.level">
        <div class="risk-top">
          <span class="badge" :class="risk.level">{{ risk.level_label }}</span>
          <span class="clause" :title="risk.clause_title">{{ risk.clause_title || '全文' }}</span>
          <span v-if="risk.check_label" class="check">{{ risk.check_label }}</span>
          <span v-if="risk.source === 'precheck'" class="source">规则预检</span>
          <span class="spacer" />
          <span v-if="risk.quote && !risk.located" class="unverified">待核对</span>
        </div>

        <blockquote v-if="risk.quote" class="quote">{{ risk.quote }}</blockquote>

        <div class="risk-body">{{ risk.risk }}</div>

        <div class="suggest">
          <span class="label">修改建议</span>
          <span class="text">{{ risk.suggestion }}</span>
        </div>

        <div v-if="risk.basis" class="basis">法律依据：{{ risk.basis }}</div>
      </div>

      <el-empty
        v-if="!filteredRisks.length"
        :description="counts.total ? '该等级下没有风险' : '未发现明显风险条款'"
        :image-size="70"
      />
    </div>

    <div class="foot">
      <span v-if="report.contract">
        已审查 {{ report.contract.char_count }} 字 / {{ report.contract.clause_count }} 条
        <template v-if="report.contract.batches > 1">，分 {{ report.contract.batches }} 批</template>
        <template v-if="report.contract.truncated">（合同过长，仅审查前部）</template>
      </span>
      <span v-if="report.disclaimer" class="disclaimer">{{ report.disclaimer }}</span>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { EditPen, WarningFilled } from '@element-plus/icons-vue'

const props = defineProps({
  report: { type: Object, required: true },
})

const level = ref('')

const counts = computed(() => ({
  high: props.report.counts?.high || 0,
  mid: props.report.counts?.mid || 0,
  low: props.report.counts?.low || 0,
  total: props.report.counts?.total || (props.report.risks || []).length,
}))

const levelClass = computed(() => {
  const map = { high: 'lv-high', mid: 'lv-mid', low: 'lv-low' }
  return map[props.report.level] || 'lv-none'
})

const missing = computed(() => props.report.missing || [])

const placeholderCount = computed(() => props.report.precheck?.placeholder_count || 0)
const placeholderSamples = computed(() =>
  (props.report.precheck?.placeholders || []).slice(0, 3).map((item) => item.sample),
)

const tabs = computed(() => [
  { value: '', label: `全部 ${counts.value.total}` },
  { value: 'high', label: `高 ${counts.value.high}` },
  { value: 'mid', label: `中 ${counts.value.mid}` },
  { value: 'low', label: `低 ${counts.value.low}` },
])

const filteredRisks = computed(() => {
  const risks = props.report.risks || []
  return level.value ? risks.filter((risk) => risk.level === level.value) : risks
})

function formatTime(value) {
  if (!value) return ''
  return String(value).replace('T', ' ').slice(0, 16)
}
</script>

<style scoped>
.review-report {
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  padding: 16px 18px;
  background: #fff;
}

/* ---------- 概览 ---------- */
.report-head {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.level-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  border-radius: 14px;
  font-size: 13px;
  font-weight: 600;
}

.level-pill .dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: currentColor;
}

.lv-high {
  color: #b42318;
  background: #fdecea;
}

.lv-mid {
  color: #a5813d;
  background: #fbf3e2;
}

.lv-low {
  color: #1f5f4a;
  background: #e8f4ef;
}

.lv-none {
  color: var(--brand-muted);
  background: #f2f3f5;
}

.counts {
  display: flex;
  gap: 6px;
}

.chip {
  font-size: 12px;
  padding: 2px 8px;
  border-radius: 10px;
  border: 1px solid transparent;
}

.chip.high {
  color: #b42318;
  background: #fdecea;
}

.chip.mid {
  color: #a5813d;
  background: #fbf3e2;
}

.chip.low {
  color: #1f5f4a;
  background: #e8f4ef;
}

.chip.total {
  color: var(--brand-muted);
  border-color: var(--brand-line);
}

.spacer {
  flex: 1;
}

.meta {
  font-size: 12px;
  color: var(--brand-muted);
}

.summary {
  margin: 12px 0 0;
  font-size: 13px;
  line-height: 1.8;
  color: var(--brand-text);
}

/* ---------- 提示 ---------- */
.alerts {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  background: #fdfaf3;
  border: 1px solid var(--brand-gold-light);
  border-radius: 8px;
  padding: 10px 12px;
}

.alert-line {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: var(--brand-text);
}

.alert-line .el-icon {
  color: var(--brand-gold-deep);
}

.alert-label {
  font-weight: 600;
}

.alert-samples {
  color: var(--brand-muted);
}

/* ---------- 筛选 ---------- */
.toolbar {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 16px 0 10px;
  flex-wrap: wrap;
}

.filters {
  display: flex;
  gap: 6px;
}

.filter {
  border: 1px solid var(--brand-line);
  background: #fff;
  color: var(--brand-text);
  font-size: 12px;
  padding: 3px 10px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.15s;
}

.filter:hover {
  border-color: var(--brand-gold);
  color: var(--brand-gold-deep);
}

.filter.active {
  background: var(--brand-navy);
  border-color: var(--brand-navy);
  color: #fff;
}

.hint {
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------- 风险条目 ---------- */
.risk-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  max-height: 640px;
  overflow-y: auto;
  padding-right: 4px;
}

.risk-item {
  border: 1px solid var(--brand-line);
  border-left: 3px solid var(--brand-line);
  border-radius: 8px;
  padding: 12px 14px;
  background: #fff;
}

.risk-item.high {
  border-left-color: #d92d20;
}

.risk-item.mid {
  border-left-color: #d9a441;
}

.risk-item.low {
  border-left-color: #4f9d7f;
}

.risk-top {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.badge {
  font-size: 11px;
  font-weight: 600;
  padding: 1px 7px;
  border-radius: 9px;
}

.badge.high {
  color: #fff;
  background: #d92d20;
}

.badge.mid {
  color: #fff;
  background: #d9a441;
}

.badge.low {
  color: #fff;
  background: #4f9d7f;
}

.clause {
  font-size: 13px;
  font-weight: 600;
  color: var(--brand-ink);
  max-width: 46%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.check {
  font-size: 11px;
  color: var(--brand-navy-soft);
  background: #eef2f8;
  padding: 1px 7px;
  border-radius: 9px;
}

.source {
  font-size: 11px;
  color: var(--brand-muted);
  border: 1px dashed var(--brand-line);
  padding: 0 6px;
  border-radius: 9px;
}

.unverified {
  font-size: 11px;
  color: #a5813d;
  background: #fbf3e2;
  padding: 1px 7px;
  border-radius: 9px;
}

.quote {
  margin: 10px 0 8px;
  padding: 8px 12px;
  border-left: 2px solid var(--brand-gold-light);
  background: #fbfbfd;
  border-radius: 0 6px 6px 0;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--brand-text);
  white-space: pre-wrap;
  word-break: break-word;
}

.risk-body {
  font-size: 13px;
  line-height: 1.8;
  color: var(--brand-ink);
}

.suggest {
  margin-top: 6px;
  font-size: 12.5px;
  line-height: 1.75;
  color: var(--brand-text);
}

.suggest .label {
  display: inline-block;
  margin-right: 6px;
  padding: 0 6px;
  font-size: 11px;
  color: var(--brand-gold-deep);
  border: 1px solid var(--brand-gold-light);
  border-radius: 4px;
}

.basis {
  margin-top: 6px;
  font-size: 12px;
  color: var(--brand-muted);
}

/* ---------- 底部 ---------- */
.foot {
  margin-top: 14px;
  padding-top: 10px;
  border-top: 1px dashed var(--brand-line);
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 11.5px;
  color: var(--brand-muted);
  line-height: 1.7;
}

.disclaimer {
  color: #a5813d;
}
</style>
