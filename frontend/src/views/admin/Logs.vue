<template>
  <div class="log-page">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <el-select v-model="query.action" placeholder="操作类型" clearable class="sel" @change="search">
        <el-option v-for="(m, k) in actionMeta" :key="k" :label="m.label" :value="k" />
      </el-select>

      <el-date-picker
        v-model="dateRange"
        type="daterange"
        range-separator="至"
        start-placeholder="开始日期"
        end-placeholder="结束日期"
        value-format="YYYY-MM-DD"
        class="range"
        @change="search"
      />

      <el-input
        v-model="query.keyword"
        placeholder="对象 / 说明 / IP / 操作人"
        clearable
        class="kw"
        @keyup.enter="search"
        @clear="search"
      >
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>

      <div class="spacer" />

      <el-button @click="reset">重置</el-button>
      <el-button type="primary" @click="search">
        <el-icon><Search /></el-icon>查询
      </el-button>
    </div>

    <!-- 列表 -->
    <el-card shadow="never" class="table-card">
      <el-table :data="rows" v-loading="loading" stripe style="width: 100%">
        <el-table-column label="操作时间" width="176">
          <template #default="{ row }">
            <span class="time">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作人" min-width="150">
          <template #default="{ row }">
            <template v-if="row.username">
              <span class="who">{{ row.real_name || row.username }}</span>
              <span class="who-acc">{{ row.username }}</span>
            </template>
            <span v-else class="muted">系统 / 匿名</span>
          </template>
        </el-table-column>

        <el-table-column label="动作" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="actionMeta[row.action]?.type || 'info'" effect="light" size="small">
              {{ actionMeta[row.action]?.label || row.action }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="对象" width="150" show-overflow-tooltip>
          <template #default="{ row }">
            <span class="mono">{{ row.target || '—' }}</span>
          </template>
        </el-table-column>

        <el-table-column label="说明" min-width="260" show-overflow-tooltip>
          <template #default="{ row }">{{ row.detail || '—' }}</template>
        </el-table-column>

        <el-table-column label="来源 IP" width="130">
          <template #default="{ row }">
            <span class="mono">{{ row.ip || '—' }}</span>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination
          v-model:current-page="query.page"
          v-model:page-size="query.page_size"
          :total="total"
          :page-sizes="[20, 50, 100]"
          layout="total, sizes, prev, pager, next"
          background
          @current-change="load"
          @size-change="search"
        />
      </div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { Search } from '@element-plus/icons-vue'
import { listLogs } from '@/api/admin'

const actionMeta = {
  login: { label: '登录', type: 'primary' },
  logout: { label: '退出', type: 'info' },
  register: { label: '注册', type: 'success' },
  create: { label: '新增', type: 'success' },
  update: { label: '修改', type: 'warning' },
  delete: { label: '删除', type: 'danger' },
  export: { label: '导出', type: 'info' },
  ai_chat: { label: 'AI 对话', type: 'info' },
}

const loading = ref(false)
const rows = ref([])
const total = ref(0)
const dateRange = ref([])

const query = reactive({
  action: '',
  keyword: '',
  page: 1,
  page_size: 20,
})

async function load() {
  loading.value = true
  try {
    const params = { ...query }
    if (!params.action) delete params.action
    if (!params.keyword) delete params.keyword
    if (dateRange.value?.length === 2) {
      params.start = dateRange.value[0]
      params.end = dateRange.value[1]
    }
    const data = await listLogs(params)
    rows.value = data.items
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function search() {
  query.page = 1
  load()
}

function reset() {
  query.action = ''
  query.keyword = ''
  dateRange.value = []
  search()
}

function formatTime(s) {
  if (!s) return '—'
  return s.replace('T', ' ').slice(0, 19)
}

load()
</script>

<style scoped>
.log-page {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.filter-bar {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-bar .sel {
  width: 140px;
}

.filter-bar .kw {
  width: 250px;
}

.filter-bar .range {
  width: 260px;
}

.spacer {
  flex: 1;
}

.table-card {
  border-radius: 12px;
}

.time {
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  color: var(--brand-text);
}

.who {
  color: var(--brand-ink);
}

.who-acc {
  margin-left: 6px;
  font-size: 12px;
  color: var(--brand-muted);
}

.mono {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--brand-muted);
}

.muted {
  color: var(--brand-muted);
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding-top: 14px;
}

@media (max-width: 1000px) {
  .filter-bar .kw,
  .filter-bar .range {
    width: 100%;
  }
}
</style>
