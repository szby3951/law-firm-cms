<template>
  <div class="dash">
    <!-- ============ 驾驶舱头部 ============ -->
    <section class="hero">
      <div class="hero-top">
        <div class="hero-title">
          <div class="eyebrow">OPERATIONS OVERVIEW</div>
          <h1>全所运营数据驾驶舱</h1>
          <p>{{ todayText }} · 数据截至 {{ generatedText }}</p>
        </div>

        <div class="hero-actions">
          <div class="seg">
            <button
              v-for="m in monthOptions"
              :key="m"
              type="button"
              :class="{ active: months === m }"
              @click="setMonths(m)"
            >
              {{ m }} 个月
            </button>
          </div>
          <button type="button" class="ghost-btn" :disabled="loading" @click="load">
            <el-icon :size="13"><Refresh /></el-icon>
            刷新
          </button>
        </div>
      </div>

      <div class="hero-metrics">
        <div v-for="m in heroMetrics" :key="m.label" class="hero-metric">
          <div class="hm-value">
            {{ m.value }}<span v-if="m.unit" class="hm-unit">{{ m.unit }}</span>
          </div>
          <div class="hm-label">{{ m.label }}</div>
        </div>
      </div>
    </section>

    <!-- ============ 指标卡 ============ -->
    <StatCards :items="kpiCards" :columns="6" :loading="loading" />

    <!-- ============ 图表区 ============ -->
    <div class="grid-main">
      <section class="panel span-8">
        <header class="panel-head">
          <div class="ph-left">
            <h3>收案与结案趋势</h3>
            <span class="ph-sub">按月统计 · 最近 {{ months }} 个月</span>
          </div>
          <div class="ph-right">
            收案 <b>{{ totalOpened }}</b> · 结案 <b>{{ totalClosed }}</b>
          </div>
        </header>
        <div class="chart-wrap">
          <VChart class="chart chart-trend" :option="trendOption" autoresize />
          <div v-if="!hasCaseData" class="chart-empty">暂无案件数据</div>
        </div>
      </section>

      <section class="panel span-4">
        <header class="panel-head">
          <div class="ph-left">
            <h3>案件状态分布</h3>
            <span class="ph-sub">当前在库案件</span>
          </div>
        </header>
        <div class="chart-wrap">
          <VChart class="chart chart-donut" :option="statusOption" autoresize />
          <div v-if="!hasCaseData" class="chart-empty">暂无案件数据</div>
        </div>
        <ul class="legend-grid">
          <li v-for="s in caseStatus" :key="s.status">
            <i :style="{ background: statusColor(s.status) }" />
            <span class="lg-name">{{ s.label }}</span>
            <span class="lg-value">{{ s.count }}</span>
          </li>
        </ul>
      </section>

      <section class="panel span-7">
        <header class="panel-head">
          <div class="ph-left">
            <h3>律师办案与创收</h3>
            <span class="ph-sub">条形为创收（按主办归属），悬停看案件量</span>
          </div>
          <div class="ph-right">共 {{ lawyerRanking.length }} 位承办律师</div>
        </header>
        <div class="chart-wrap">
          <VChart
            class="chart chart-rank"
            :style="{ height: `${rankHeight}px` }"
            :option="rankOption"
            autoresize
          />
          <div v-if="!lawyerRanking.length" class="chart-empty">暂无承办数据</div>
        </div>
      </section>

      <section class="panel span-5">
        <header class="panel-head">
          <div class="ph-left">
            <h3>客户来源构成</h3>
            <span class="ph-sub">在册客户 {{ kpi.clients }} 位</span>
          </div>
        </header>

        <div class="source-body">
          <div class="source-bar">
            <span
              v-for="(s, i) in clientSource"
              :key="s.name"
              :style="{ width: `${s.ratio}%`, background: sourceColor(i) }"
              :title="`${s.name} ${s.count}`"
            />
          </div>

          <ul class="source-list">
            <li v-for="(s, i) in clientSource" :key="s.name">
              <i :style="{ background: sourceColor(i) }" />
              <span class="sl-name">{{ s.name }}</span>
              <span class="sl-count">{{ s.count }}</span>
              <span class="sl-ratio">{{ s.ratio }}%</span>
            </li>
          </ul>

          <div v-if="!clientSource.length" class="chart-empty static">暂无客户数据</div>
        </div>
      </section>

      <section class="panel span-7">
        <header class="panel-head">
          <div class="ph-left">
            <h3>案由分布</h3>
            <span class="ph-sub">前 {{ caseCause.length }} 类 · 占比按全所案件计算</span>
          </div>
          <div class="ph-right">共 {{ kpi.total_cases }} 件</div>
        </header>
        <div class="chart-wrap">
          <VChart class="chart chart-cause" :option="causeOption" autoresize />
          <div v-if="!caseCause.length" class="chart-empty">暂无案由数据</div>
        </div>
      </section>

      <section class="panel span-5">
        <header class="panel-head">
          <div class="ph-left">
            <h3>营收与回款</h3>
            <span class="ph-sub">统计月份 {{ billing.month || '—' }}</span>
          </div>
          <div class="ph-right">
            <span class="rate-pill" :class="rateLevel">{{ rateLabel }}</span>
          </div>
        </header>

        <div class="rev-body">
          <div class="rev-hero">
            <div class="rev-label">本月实收</div>
            <div class="rev-value">{{ money(billing.month_income) }}</div>
          </div>

          <div class="rev-progress">
            <div class="rp-head">
              <span>回款率</span>
              <b>{{ rateText }}</b>
            </div>
            <div class="rp-bar">
              <div class="rp-fill" :style="{ width: `${Math.min(billing.collection_rate || 0, 100)}%` }" />
            </div>
            <div class="rp-foot">
              <span>已收 {{ money(billing.total_paid) }}</span>
              <span>应收 {{ money(billing.total_due) }}</span>
            </div>
          </div>

          <div class="rev-grid">
            <div>
              <span>累计应收</span>
              <b>{{ money(billing.total_due) }}</b>
            </div>
            <div>
              <span>累计已收</span>
              <b class="ok">{{ money(billing.total_paid) }}</b>
            </div>
            <div>
              <span>待收</span>
              <b class="warn">{{ money(billing.total_unpaid) }}</b>
            </div>
          </div>

          <div v-if="billing.overdue_count" class="rev-alert">
            <el-icon :size="13"><Warning /></el-icon>
            逾期 {{ billing.overdue_count }} 期，合计 {{ money(billing.overdue_amount) }}
          </div>
        </div>
      </section>
    </div>

    <!-- ============ 预警带 ============ -->
    <div class="alert-strip">
      <div v-for="a in alerts" :key="a.label" class="alert-item" :class="a.tone">
        <div class="ai-value">{{ a.value }}</div>
        <div class="ai-text">
          <div class="ai-label">{{ a.label }}</div>
          <div class="ai-hint">{{ a.hint }}</div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { Refresh, Warning } from '@element-plus/icons-vue'
import { use } from 'echarts/core'
import { graphic } from 'echarts/core'
import { CanvasRenderer } from 'echarts/renderers'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import {
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
} from 'echarts/components'
import VChart from 'vue-echarts'

import StatCards from '@/components/StatCards.vue'
import { getDashboard } from '@/api/stats'

use([
  CanvasRenderer,
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
])

/* ---------------------------------------------------------------- 配色 */
const C = {
  navy: '#14213d',
  navySoft: '#1d2b47',
  ink: '#22304d',
  gold: '#c9a55c',
  goldLight: '#e8c98a',
  green: '#1D9E75',
  rose: '#993556',
  slate: '#8a93a6',
  line: '#eef0f4',
}

const STATUS_COLORS = {
  consulting: '#93a0bb',
  filed: '#c9a55c',
  handling: '#1d2b47',
  pending_close: '#6c7ea3',
  closed: '#1D9E75',
  withdrawn: '#c9ceda',
}

const SOURCE_COLORS = [
  '#14213d',
  '#c9a55c',
  '#1D9E75',
  '#993556',
  '#6c7ea3',
  '#e8c98a',
  '#93a0bb',
  '#4c5f85',
]

// 图表统一字体：与页面字体保持一致，避免 canvas 回落到默认 sans-serif
const FONT = {
  fontFamily: "PingFang SC, Microsoft YaHei, -apple-system, 'Segoe UI', sans-serif",
}

/* ---------------------------------------------------------------- 状态 */
const monthOptions = [6, 12, 24]
const months = ref(12)
const loading = ref(false)
const raw = ref(null)

const kpi = computed(() => raw.value?.kpi || {})
const caseTrend = computed(() => raw.value?.case_trend || [])
const caseStatus = computed(() => raw.value?.case_status || [])
const caseCause = computed(() => raw.value?.case_cause || [])
const lawyerRanking = computed(() => raw.value?.lawyer_ranking || [])
const clientSource = computed(() => raw.value?.client_source || [])
const billing = computed(() => raw.value?.billing || {})
const expiring = computed(() => raw.value?.expiring || {})
const todo = computed(() => raw.value?.todo || {})

const hasCaseData = computed(
  () => Number(kpi.value.total_cases || 0) > 0 || caseTrend.value.some((p) => p.opened || p.closed),
)

/* ---------------------------------------------------------------- 文本 */
function fmtInt(v) {
  return Number(v || 0).toLocaleString('zh-CN')
}

function money(v) {
  return `¥${Number(v || 0).toLocaleString('zh-CN', { maximumFractionDigits: 0 })}`
}

function fmtTime(s) {
  if (!s) return '—'
  const d = new Date(s)
  if (Number.isNaN(d.getTime())) return String(s).slice(0, 16).replace('T', ' ')
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const todayText = new Date().toLocaleDateString('zh-CN', {
  year: 'numeric',
  month: 'long',
  day: 'numeric',
  weekday: 'long',
})

const generatedText = computed(() => fmtTime(raw.value?.generated_at))

const rateText = computed(() => `${Number(billing.value.collection_rate || 0).toFixed(1)}%`)

const rateLevel = computed(() => {
  if (!Number(billing.value.total_due || 0)) return 'none'
  return Number(billing.value.collection_rate || 0) >= 60 ? 'good' : 'warn'
})

const rateLabel = computed(() => {
  if (rateLevel.value === 'none') return '暂无应收'
  return rateLevel.value === 'good' ? '回款良好' : '回款偏低'
})

/* ---------------------------------------------------------------- 指标 */
const heroMetrics = computed(() => [
  { label: '在办案件', value: fmtInt(kpi.value.active_cases), unit: '件' },
  { label: '本月实收', value: money(billing.value.month_income), unit: '' },
  { label: '回款率', value: Number(billing.value.collection_rate || 0).toFixed(1), unit: '%' },
  { label: '在册客户', value: fmtInt(kpi.value.clients), unit: '位' },
])

const kpiCards = computed(() => {
  const total = Number(kpi.value.total_cases || 0)
  const closed = Number(kpi.value.closed_cases || 0)
  const closeRate = total ? ((closed / total) * 100).toFixed(1) : '0.0'
  return [
    {
      label: '累计案件',
      value: fmtInt(total),
      unit: '件',
      icon: 'Suitcase',
      tone: 'navy',
      hint: `含已结案 ${fmtInt(closed)} 件`,
    },
    {
      label: '已结案',
      value: fmtInt(closed),
      unit: '件',
      icon: 'CircleCheck',
      tone: 'green',
      hint: `结案率 ${closeRate}%`,
    },
    {
      label: '本月新增客户',
      value: fmtInt(kpi.value.new_clients),
      unit: '位',
      icon: 'UserFilled',
      tone: 'gold',
      hint: `客户总数 ${fmtInt(kpi.value.clients)} 位`,
    },
    {
      label: '30 天内到期合同',
      value: fmtInt(kpi.value.expiring_contracts),
      unit: '份',
      icon: 'Warning',
      tone: 'rose',
      hint: `7 天内 ${fmtInt(expiring.value.within_7)} 份`,
    },
    {
      label: '今日待办',
      value: fmtInt(kpi.value.today_todos),
      unit: '项',
      icon: 'Calendar',
      tone: 'slate',
      hint: `未来 7 天 ${fmtInt(kpi.value.week_todos)} 项`,
    },
    {
      label: '逾期未收',
      value: fmtInt(billing.value.overdue_count),
      unit: '期',
      icon: 'Money',
      tone: 'rose',
      hint: money(billing.value.overdue_amount).replace('¥', '逾期 ¥'),
    },
  ]
})

const alerts = computed(() => [
  {
    tone: 'rose',
    value: fmtInt(expiring.value.within_7),
    label: '7 天内到期合同',
    hint: '需尽快续签或终止',
  },
  {
    tone: 'gold',
    value: fmtInt(expiring.value.within_30),
    label: '30 天内到期合同',
    hint: `60 天内共 ${fmtInt(expiring.value.within_60)} 份`,
  },
  {
    tone: 'navy',
    value: fmtInt(todo.value.overdue),
    label: '逾期未办日程',
    hint: `今日 ${fmtInt(todo.value.today)} 项待办`,
  },
  {
    tone: 'slate',
    value: fmtInt(billing.value.overdue_count),
    label: '逾期未收期次',
    hint: `${money(billing.value.overdue_amount)} 待催收`,
  },
])

/* ---------------------------------------------------------------- 图表 */
const totalOpened = computed(() => caseTrend.value.reduce((s, p) => s + p.opened, 0))
const totalClosed = computed(() => caseTrend.value.reduce((s, p) => s + p.closed, 0))

const tooltipStyle = {
  backgroundColor: 'rgba(20, 33, 61, 0.94)',
  borderWidth: 0,
  padding: [8, 12],
  textStyle: { color: '#fff', fontSize: 12 },
  extraCssText: 'border-radius:8px;box-shadow:0 8px 24px rgba(13,23,48,.28);',
}

const trendOption = computed(() => ({
  textStyle: FONT,
  grid: { left: 4, right: 16, top: 36, bottom: 2, containLabel: true },
  tooltip: { ...tooltipStyle, trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: C.gold, type: 'dashed' } } },
  legend: {
    right: 0,
    top: 2,
    itemWidth: 16,
    itemHeight: 2,
    icon: 'rect',
    textStyle: { color: C.slate, fontSize: 11 },
    data: ['收案', '结案'],
  },
  xAxis: {
    type: 'category',
    data: caseTrend.value.map((p) => p.label),
    boundaryGap: false,
    axisLine: { lineStyle: { color: '#e8eaf0' } },
    axisTick: { show: false },
    axisLabel: { color: '#9aa2b1', fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    minInterval: 1,
    splitLine: { lineStyle: { color: C.line, type: 'dashed' } },
    axisLabel: { color: '#9aa2b1', fontSize: 11 },
  },
  series: [
    {
      name: '收案',
      type: 'line',
      smooth: 0.35,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: false,
      lineStyle: { width: 2.2, color: C.navy },
      itemStyle: { color: C.navy },
      areaStyle: {
        color: new graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(20, 33, 61, 0.16)' },
          { offset: 1, color: 'rgba(20, 33, 61, 0)' },
        ]),
      },
      data: caseTrend.value.map((p) => p.opened),
    },
    {
      name: '结案',
      type: 'line',
      smooth: 0.35,
      symbol: 'circle',
      symbolSize: 6,
      showSymbol: false,
      lineStyle: { width: 2, color: C.gold, type: 'dashed' },
      itemStyle: { color: C.gold },
      data: caseTrend.value.map((p) => p.closed),
    },
  ],
}))

function statusColor(status) {
  return STATUS_COLORS[status] || C.slate
}

const statusOption = computed(() => {
  const total = caseStatus.value.reduce((s, x) => s + x.count, 0)
  return {
    textStyle: FONT,
    tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}：{c} 件（{d}%）' },
    title: {
      text: fmtInt(total),
      subtext: '案件总数',
      left: 'center',
      top: '32%',
      textStyle: { fontSize: 30, fontWeight: 600, color: C.ink },
      subtextStyle: { fontSize: 11, color: C.slate, lineHeight: 22 },
      itemGap: 4,
    },
    series: [
      {
        type: 'pie',
        radius: ['64%', '82%'],
        center: ['50%', '46%'],
        avoidLabelOverlap: true,
        itemStyle: { borderColor: '#fff', borderWidth: 2, borderRadius: 3 },
        label: { show: false },
        labelLine: { show: false },
        emphasis: { scale: true, scaleSize: 4 },
        data: caseStatus.value
          .filter((s) => s.count > 0)
          .map((s) => ({
            name: s.label,
            value: s.count,
            itemStyle: { color: statusColor(s.status) },
          })),
      },
    ],
  }
})

// 条形图高度随人数自适应：只有一两位律师时不留大片空白，人多时撑高
const rankHeight = computed(() => {
  const n = lawyerRanking.value.length
  if (!n) return 160
  return Math.min(300, Math.max(180, n * 36 + 24))
})

const rankOption = computed(() => {  const rows = lawyerRanking.value
  const max = Math.max(...rows.map((r) => Number(r.income || 0)), 1)
  return {
    textStyle: FONT,
    grid: { left: 4, right: 78, top: 8, bottom: 0, containLabel: true },
    tooltip: {
      ...tooltipStyle,
      trigger: 'item',
      formatter: (p) => {
        const row = rows[p.dataIndex]
        if (!row) return ''
        return [
          `<b>${row.name}</b>`,
          `创收：${money(row.income)}`,
          `承办：${row.case_count} 件（主办 ${row.lead_count} / 协办 ${row.assist_count}）`,
          `在办 ${row.active_count} · 结案 ${row.closed_count}`,
        ].join('<br/>')
      },
    },
    xAxis: { type: 'value', show: false, max: max * 1.35 },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.name),
      inverse: true,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: '#2a3347', fontSize: 12 },
    },
    series: [
      {
        type: 'bar',
        barWidth: 14,
        data: rows.map((r) => Number(r.income || 0)),
        itemStyle: {
          borderRadius: [0, 7, 7, 0],
          color: new graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: C.gold },
            { offset: 1, color: C.goldLight },
          ]),
        },
        label: {
          show: true,
          position: 'right',
          formatter: (p) => money(p.value),
          color: C.slate,
          fontSize: 11,
        },
      },
    ],
  }
})

const causeOption = computed(() => {
  const rows = [...caseCause.value].reverse()
  return {
    textStyle: FONT,
    grid: { left: 4, right: 46, top: 6, bottom: 0, containLabel: true },
    tooltip: { ...tooltipStyle, trigger: 'item', formatter: '{b}：{c} 件' },
    xAxis: { type: 'value', show: false },
    yAxis: {
      type: 'category',
      data: rows.map((r) => r.name),
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: '#2a3347',
        fontSize: 12,
        width: 96,
        overflow: 'truncate',
      },
    },
    series: [
      {
        type: 'bar',
        barWidth: 10,
        data: rows.map((r) => r.count),
        itemStyle: {
          borderRadius: [0, 5, 5, 0],
          color: new graphic.LinearGradient(0, 0, 1, 0, [
            { offset: 0, color: C.navy },
            { offset: 1, color: '#4c5f85' },
          ]),
        },
        label: {
          show: true,
          position: 'right',
          formatter: '{c}',
          color: C.slate,
          fontSize: 11,
        },
      },
    ],
  }
})

function sourceColor(index) {
  return SOURCE_COLORS[index % SOURCE_COLORS.length]
}

/* ---------------------------------------------------------------- 加载 */
function setMonths(m) {
  if (months.value === m) return
  months.value = m
  load()
}

async function load() {
  loading.value = true
  try {
    raw.value = await getDashboard({ months: months.value })
  } catch {
    ElMessage.error('统计数据加载失败，请稍后重试')
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.dash {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

/* ---------------- 驾驶舱头部 ---------------- */
.hero {
  position: relative;
  overflow: hidden;
  border-radius: 16px;
  padding: 22px 26px 20px;
  background:
    radial-gradient(1200px 300px at 88% -40%, rgba(201, 165, 92, 0.16), transparent 62%),
    linear-gradient(118deg, #0d1730 0%, #14213d 46%, #1d2b47 100%);
  color: #fff;
}

.hero::after {
  content: '';
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(201, 165, 92, 0.5), transparent);
}

.hero-top {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.eyebrow {
  font-size: 10px;
  letter-spacing: 3px;
  color: rgba(232, 201, 138, 0.85);
  font-weight: 500;
}

.hero-title h1 {
  margin: 6px 0 4px;
  font-size: 21px;
  font-weight: 600;
  letter-spacing: 2px;
}

.hero-title p {
  margin: 0;
  font-size: 12px;
  color: rgba(255, 255, 255, 0.44);
  letter-spacing: 0.4px;
}

.hero-actions {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-shrink: 0;
}

.seg {
  display: inline-flex;
  padding: 3px;
  border-radius: 9px;
  background: rgba(255, 255, 255, 0.07);
  border: 1px solid rgba(255, 255, 255, 0.08);
}

.seg button {
  border: none;
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
  padding: 5px 12px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.16s;
  font-family: inherit;
}

.seg button:hover {
  color: #fff;
}

.seg button.active {
  background: rgba(201, 165, 92, 0.9);
  color: #14213d;
  font-weight: 600;
}

.ghost-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  height: 30px;
  padding: 0 13px;
  border-radius: 8px;
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.16);
  color: rgba(255, 255, 255, 0.72);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.16s;
  font-family: inherit;
}

.ghost-btn:hover:not(:disabled) {
  border-color: rgba(201, 165, 92, 0.6);
  color: var(--brand-gold-light);
}

.ghost-btn:disabled {
  opacity: 0.5;
  cursor: default;
}

.hero-metrics {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.08);
}

.hero-metric {
  padding-left: 20px;
  border-left: 1px solid rgba(255, 255, 255, 0.08);
}

.hero-metric:first-child {
  padding-left: 0;
  border-left: none;
}

.hm-value {
  font-size: 26px;
  font-weight: 600;
  letter-spacing: -0.5px;
  font-variant-numeric: tabular-nums;
  color: #fff;
  line-height: 1.15;
}

.hm-unit {
  font-size: 12px;
  font-weight: 400;
  color: rgba(232, 201, 138, 0.9);
  margin-left: 4px;
  letter-spacing: 0;
}

.hm-label {
  margin-top: 5px;
  font-size: 11px;
  color: rgba(255, 255, 255, 0.45);
  letter-spacing: 0.6px;
}

/* ---------------- 栅格 ---------------- */
.grid-main {
  display: grid;
  grid-template-columns: repeat(12, 1fr);
  gap: 14px;
}

.span-4 {
  grid-column: span 4;
}

.span-5 {
  grid-column: span 5;
}

.span-7 {
  grid-column: span 7;
}

.span-8 {
  grid-column: span 8;
}

.panel {
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 14px;
  padding: 16px 18px 14px;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 6px;
}

.panel-head h3 {
  position: relative;
  margin: 0;
  padding-left: 10px;
  font-size: 13.5px;
  font-weight: 600;
  color: var(--brand-ink);
  letter-spacing: 0.4px;
}

.panel-head h3::before {
  content: '';
  position: absolute;
  left: 0;
  top: 2px;
  bottom: 2px;
  width: 2px;
  border-radius: 1px;
  background: var(--brand-gold);
}

.ph-sub {
  display: block;
  margin: 5px 0 0 10px;
  font-size: 11px;
  color: var(--brand-muted);
}

.ph-right {
  font-size: 11px;
  color: var(--brand-muted);
  white-space: nowrap;
  padding-top: 2px;
}

.ph-right b {
  color: var(--brand-ink);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.rate-pill {
  display: inline-block;
  font-size: 11px;
  line-height: 18px;
  padding: 0 9px;
  border-radius: 9px;
  letter-spacing: 0.3px;
  white-space: nowrap;
}

.rate-pill.good {
  background: #eaf5ef;
  color: #1D9E75;
}

.rate-pill.warn {
  background: #faf3e7;
  color: var(--brand-gold-deep);
}

.rate-pill.none {
  background: #f0f2f6;
  color: var(--brand-muted);
}

.chart-wrap {
  position: relative;
  flex: 1;
  min-height: 0;
}

.chart {
  width: 100%;
}

.chart-trend {
  height: 250px;
}

.chart-donut {
  height: 186px;
}

.chart-rank {
  height: 236px;
}
.chart-cause {
  height: 268px;
}

.chart-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  color: var(--brand-muted);
  background: rgba(255, 255, 255, 0.72);
  letter-spacing: 0.5px;
}

.chart-empty.static {
  position: static;
  background: transparent;
  padding: 30px 0;
}

/* ---------------- 状态图例 ---------------- */
.legend-grid {
  list-style: none;
  margin: 8px 0 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 6px 14px;
}

.legend-grid li {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
  color: var(--brand-text);
}

.legend-grid i {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex-shrink: 0;
}

.lg-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.lg-value {
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

/* ---------------- 客户来源 ---------------- */
.source-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 8px;
  flex: 1;
}

.source-bar {
  display: flex;
  height: 10px;
  border-radius: 5px;
  overflow: hidden;
  background: #f0f2f6;
}

.source-bar span {
  height: 100%;
  transition: width 0.4s ease;
}

.source-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 9px 16px;
}

.source-list li {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: 12px;
}

.source-list i {
  width: 7px;
  height: 7px;
  border-radius: 2px;
  flex-shrink: 0;
}

.sl-name {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--brand-text);
}

.sl-count {
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

.sl-ratio {
  width: 46px;
  text-align: right;
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

/* ---------------- 营收 ---------------- */
.rev-body {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding-top: 8px;
  flex: 1;
}

.rev-hero {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  padding-bottom: 12px;
  border-bottom: 1px dashed var(--brand-line);
}

.rev-label {
  font-size: 12px;
  color: var(--brand-muted);
  letter-spacing: 0.6px;
}

.rev-value {
  font-size: 26px;
  font-weight: 600;
  color: var(--brand-navy);
  font-variant-numeric: tabular-nums;
  letter-spacing: -0.5px;
}

.rev-progress {
  display: flex;
  flex-direction: column;
  gap: 7px;
}

.rp-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  font-size: 12px;
  color: var(--brand-muted);
}

.rp-head b {
  font-size: 14px;
  color: var(--brand-gold-deep);
  font-variant-numeric: tabular-nums;
}

.rp-bar {
  height: 8px;
  border-radius: 4px;
  background: #f0f2f6;
  overflow: hidden;
}

.rp-fill {
  height: 100%;
  border-radius: 3px;
  background: linear-gradient(90deg, var(--brand-gold), var(--brand-gold-light));
  transition: width 0.5s ease;
}

.rp-foot {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--brand-muted);
  font-variant-numeric: tabular-nums;
}

.rev-grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
}

.rev-grid div {
  background: #fafbfc;
  border: 1px solid #f0f2f6;
  border-radius: 9px;
  padding: 9px 11px;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.rev-grid span {
  font-size: 11px;
  color: var(--brand-muted);
}

.rev-grid b {
  font-size: 14px;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
}

.rev-grid b.ok {
  color: #1D9E75;
}

.rev-grid b.warn {
  color: #993556;
}

.rev-alert {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 11px;
  border-radius: 8px;
  background: #faeef0;
  color: #993556;
  font-size: 12px;
}

/* ---------------- 预警带 ---------------- */
.alert-strip {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 14px;
}

.alert-item {
  display: flex;
  align-items: center;
  gap: 14px;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  padding: 13px 18px;
  position: relative;
  overflow: hidden;
}

.alert-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 14px;
  bottom: 14px;
  width: 2px;
  border-radius: 1px;
  background: var(--brand-slate, #8a93a6);
}

.alert-item.rose::before {
  background: #993556;
}

.alert-item.gold::before {
  background: var(--brand-gold);
}

.alert-item.navy::before {
  background: var(--brand-navy);
}

.ai-value {
  font-size: 22px;
  font-weight: 600;
  color: var(--brand-ink);
  font-variant-numeric: tabular-nums;
  min-width: 34px;
}

.ai-label {
  font-size: 12px;
  color: var(--brand-text);
}

.ai-hint {
  margin-top: 3px;
  font-size: 11px;
  color: var(--brand-muted);
}

/* ---------------- 响应式 ---------------- */
@media (max-width: 1400px) {
  .chart-cause {
    height: 240px;
  }
}

@media (max-width: 1200px) {
  .span-4,
  .span-5,
  .span-7,
  .span-8 {
    grid-column: span 12;
  }

  .alert-strip {
    grid-template-columns: repeat(2, 1fr);
  }
}

@media (max-width: 820px) {
  .hero-metrics {
    grid-template-columns: repeat(2, 1fr);
    row-gap: 16px;
  }

  .hero-metric:nth-child(3) {
    padding-left: 0;
    border-left: none;
  }

  .hero-top {
    flex-direction: column;
  }
}
</style>
