<template>
  <div class="history-pop">
    <div class="pop-title">
      {{ title }}
      <span v-if="list.length" class="pop-count">{{ list.length }}</span>
    </div>

    <el-empty
      v-if="!loading && !list.length"
      :description="emptyText"
      :image-size="60"
    />

    <el-scrollbar v-else max-height="320px">
      <div
        v-for="item in list"
        :key="item.id"
        class="pop-item"
        :class="{ active: item.id === activeId }"
        @click="emit('select', item.id)"
      >
        <div class="pop-main">
          <div class="pop-item-title" :title="item.title || fallbackTitle">
            {{ item.title || fallbackTitle }}
          </div>
          <div class="pop-item-time">
            {{ relativeTime(item.updated_at) }}
            <span v-if="item.message_count">· {{ item.message_count }} 条</span>
          </div>
        </div>
        <el-icon class="pop-del" title="删除这条记录" @click.stop="remove(item)">
          <Delete />
        </el-icon>
      </div>
    </el-scrollbar>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Delete } from '@element-plus/icons-vue'
import { deleteAiSession, listAiSessions } from '@/api/ai'
import { relativeTime } from '@/utils/schedule'

/**
 * 客户端用的轻量历史列表（popover 内）。
 *
 * 两个入口各传自己的 `sessionType`，列表只出本入口的会话——督办记录里全是
 * 金额与进度，混进法律问答的历史会被当成法律事实读。
 */
const props = defineProps({
  title: { type: String, default: '最近对话' },
  emptyText: { type: String, default: '还没有历史对话' },
  fallbackTitle: { type: String, default: '未命名会话' },
  sessionType: { type: String, default: '' },
  activeId: { type: Number, default: null },
})

const emit = defineEmits(['select', 'deleted'])

const list = ref([])
const loading = ref(false)

async function reload() {
  loading.value = true
  try {
    const data = await listAiSessions({
      page: 1,
      page_size: 20,
      ...(props.sessionType ? { type: props.sessionType } : {}),
    })
    list.value = data.items || []
  } catch {
    // 列表失败不阻塞对话，错误已由请求拦截器提示
    list.value = []
  } finally {
    loading.value = false
  }
}

async function remove(item) {
  try {
    await ElMessageBox.confirm(
      `删除后这条对话的全部问答记录都会移除，且不可恢复。确定删除「${item.title || props.fallbackTitle}」吗？`,
      '删除对话',
      { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }

  try {
    await deleteAiSession(item.id)
    ElMessage.success('对话已删除')
    // 删的是当前正在看的那条：先让父组件清空，再刷新列表，
    // 否则输入框还挂着已不存在的会话 id，追问会 404
    if (item.id === props.activeId) emit('select', null)
    emit('deleted', item.id)
    await reload()
  } catch {
    /* 错误已由拦截器提示 */
  }
}

defineExpose({ reload })

// popover 内容首次展开才挂载，@show 那一刻 ref 可能还没就绪，
// 这里自己拉一次，父组件的 @show 只作为再次展开时的刷新
onMounted(reload)
</script>

<style scoped>
.history-pop {
  margin: -4px;
}

.pop-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 4px 8px 8px;
  font-size: 12px;
  color: var(--brand-muted);
}

.pop-count {
  font-size: 11px;
  color: var(--brand-muted);
}

.pop-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 9px;
  border-radius: 8px;
  cursor: pointer;
}

.pop-item:hover {
  background: var(--brand-bg);
}

.pop-item.active {
  background: rgba(201, 165, 92, 0.12);
}

.pop-main {
  min-width: 0;
  flex: 1;
}

.pop-item-title {
  font-size: 13px;
  color: var(--brand-ink);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.pop-item-time {
  font-size: 11px;
  color: var(--brand-muted);
  margin-top: 2px;
}

.pop-del {
  flex: none;
  font-size: 13px;
  color: var(--brand-muted);
  /* 常显但压暗：客户不熟悉界面，隐藏到 hover 才出现的删除键基本等于没有 */
  opacity: 0.5;
  transition: opacity 0.15s;
}

.pop-item:hover .pop-del {
  opacity: 1;
}

.pop-del:hover {
  color: var(--brand-gold-deep, #b8934a);
}
</style>
