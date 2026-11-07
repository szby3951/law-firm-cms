<template>
  <div class="session-list">
    <div class="list-head">
      <el-button type="primary" class="new-btn" @click="emit('new')">
        <el-icon><Plus /></el-icon>新建对话
      </el-button>
    </div>

    <div class="list-search">
      <el-input v-model="keyword" placeholder="搜索历史会话" clearable size="small">
        <template #prefix><el-icon><Search /></el-icon></template>
      </el-input>
    </div>

    <el-scrollbar v-loading="loading" class="list-body">
      <el-empty
        v-if="!loading && !filtered.length"
        :description="keyword ? '没有匹配的会话' : emptyText"
        :image-size="72"
      />

      <div
        v-for="item in filtered"
        :key="item.id"
        class="session-item"
        :class="{ active: item.id === activeId }"
        @click="emit('select', item.id)"
      >
        <el-icon class="s-icon" :size="15">
          <component :is="isBusiness ? DataLine : ChatLineSquare" />
        </el-icon>
        <div class="s-main">
          <div class="s-title" :title="item.title || '未命名会话'">
            {{ item.title || '未命名会话' }}
          </div>
          <div class="s-meta">
            <span>{{ relativeTime(item.updated_at) }}</span>
            <span v-if="item.message_count">{{ item.message_count }} 条</span>
          </div>
        </div>
        <el-icon
          class="s-del"
          :title="'删除会话'"
          @click.stop="remove(item)"
        >
          <Delete />
        </el-icon>
      </div>
    </el-scrollbar>

    <div class="list-foot">
      共 {{ total }} 个会话 · 仅本人可见
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ChatLineSquare, DataLine, Delete, Plus, Search } from '@element-plus/icons-vue'
import { deleteAiSession, listAiSessions } from '@/api/ai'
import { relativeTime } from '@/utils/schedule'

const props = defineProps({
  activeId: { type: Number, default: null },
  // 两类会话共用一个列表组件，但要各自过滤，否则法律问答的历史里会混进
  // 一堆「我还差多少钱」的业务查询。
  sessionType: { type: String, default: '' },
  variant: { type: String, default: 'chat' },
})
const emit = defineEmits(['select', 'new', 'deleted'])

const isBusiness = computed(() => props.variant === 'business')
const emptyText = computed(() =>
  isBusiness.value ? '还没有查询记录' : '还没有咨询记录',
)

const sessions = ref([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')

const filtered = computed(() => {
  const kw = keyword.value.trim()
  if (!kw) return sessions.value
  return sessions.value.filter((item) => (item.title || '').includes(kw))
})

async function reload() {
  loading.value = true
  try {
    const data = await listAiSessions({
      page: 1,
      page_size: 50,
      ...(props.sessionType ? { type: props.sessionType } : {}),
    })
    sessions.value = data.items || []
    total.value = data.total || 0
  } catch {
    // 列表失败不阻塞问答：错误已由请求拦截器提示
  } finally {
    loading.value = false
  }
}

async function remove(item) {
  try {
    await ElMessageBox.confirm(
      `删除后该会话的全部问答与引用记录都将移除，且不可恢复。确定删除「${item.title || '未命名会话'}」吗？`,
      '删除会话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await deleteAiSession(item.id)
    ElMessage.success('会话已删除')
    if (item.id === props.activeId) emit('select', null)
    emit('deleted', item.id)
    await reload()
  } catch {
    /* 错误已由拦截器提示 */
  }
}

onMounted(reload)

defineExpose({ reload })
</script>

<style scoped>
.session-list {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: #fff;
  border: 1px solid var(--brand-line);
  border-radius: 12px;
  overflow: hidden;
}

.list-head {
  padding: 14px 14px 10px;
}

.new-btn {
  width: 100%;
}

.list-search {
  padding: 0 14px 10px;
}

.list-body {
  flex: 1;
  min-height: 0;
}

.session-item {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 10px 4px;
  padding: 9px 10px;
  border-radius: 9px;
  cursor: pointer;
  transition: background 0.15s;
}

.session-item:hover {
  background: var(--brand-bg);
}

.session-item.active {
  background: rgba(201, 165, 92, 0.12);
}

.session-item.active .s-icon {
  color: var(--brand-gold-deep);
}

.s-icon {
  flex-shrink: 0;
  color: var(--brand-muted);
}

.s-main {
  flex: 1;
  min-width: 0;
}

.s-title {
  font-size: 13px;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.s-meta {
  display: flex;
  gap: 8px;
  margin-top: 3px;
  font-size: 11px;
  color: var(--brand-muted);
}

.s-del {
  flex-shrink: 0;
  font-size: 13px;
  color: var(--brand-muted);
  opacity: 0;
  transition: opacity 0.15s;
}

.session-item:hover .s-del {
  opacity: 1;
}

.s-del:hover {
  color: #c45656;
}

.list-foot {
  padding: 8px 14px;
  font-size: 11px;
  color: var(--brand-muted);
  border-top: 1px solid var(--brand-line);
  background: #fcfcfd;
}
</style>
