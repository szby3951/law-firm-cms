<template>
  <div class="rich-editor" :style="{ height }">
    <Toolbar
      class="editor-toolbar"
      :editor="editorRef"
      :default-config="toolbarConfig"
      mode="default"
    />
    <Editor
      v-model="html"
      class="editor-body"
      :default-config="editorConfig"
      mode="default"
      @on-created="handleCreated"
    />
  </div>
</template>

<script setup>
import { nextTick, onBeforeUnmount, ref, shallowRef, watch } from 'vue'
import { ElMessage } from 'element-plus'
import '@wangeditor/editor/dist/css/style.css'
import { Editor, Toolbar } from '@wangeditor/editor-for-vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  height: { type: String, default: '620px' },
  placeholder: { type: String, default: '请输入文书正文，可从右侧插入模板变量…' },
})

const emit = defineEmits(['update:modelValue', 'ready'])

const editorRef = shallowRef(null)
const html = ref(props.modelValue || '')

// 工具栏：法律文书用不到视频，其余保留（含表格、图片、字号、对齐）
const toolbarConfig = {
  excludeKeys: ['group-video', 'insertVideo', 'uploadVideo'],
}

// 图片走 base64 内嵌，避免额外上传接口，也能被后端 docx 导出识别
function customUpload(file, insertFn) {
  if (file.size > 5 * 1024 * 1024) {
    ElMessage.warning('图片不能超过 5MB')
    return
  }
  const reader = new FileReader()
  reader.onload = () => insertFn(reader.result, file.name, reader.result)
  reader.readAsDataURL(file)
}

const editorConfig = {
  placeholder: props.placeholder,
  MENU_CONF: {
    uploadImage: { customUpload },
    insertImage: { base64LimitSize: 5 * 1024 * 1024 },
  },
}

function handleCreated(editor) {
  editorRef.value = editor
  // 编辑器初始化时可能对 HTML 做规范化（例如补齐 <p>），此时通知父组件
  // 重新取基线快照，避免刚打开就被判定为「有未保存修改」
  nextTick(() => emit('ready', editor))
}

watch(
  () => props.modelValue,
  (value) => {
    if ((value || '') !== html.value) {
      html.value = value || ''
    }
  },
)

watch(html, (value) => {
  if (value !== props.modelValue) {
    emit('update:modelValue', value)
  }
})

function insertText(text) {
  const editor = editorRef.value
  if (!editor) return
  editor.restoreSelection()
  editor.insertText(text)
  editor.focus()
}

defineExpose({ insertText, focus: () => editorRef.value?.focus() })

onBeforeUnmount(() => {
  // wangEditor 必须手动销毁，否则会在路由切换后残留 DOM 与事件
  editorRef.value?.destroy()
  editorRef.value = null
})
</script>

<style scoped>
.rich-editor {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--brand-line);
  border-radius: 10px;
  overflow: hidden;
  background: #fff;
}

.editor-toolbar {
  border-bottom: 1px solid var(--brand-line);
  background: #fafbfd;
}

.editor-body {
  flex: 1;
  overflow-y: hidden;
}

/* 编辑区排版贴近 A4 公文：宋体、稍大行距 */
.rich-editor :deep(.w-e-text-container) {
  background: #fff;
}

.rich-editor :deep(.w-e-text-container [data-slate-editor]) {
  font-family: 'Songti SC', SimSun, 'PingFang SC', 'Microsoft YaHei', serif;
  font-size: 15px;
  line-height: 1.9;
  color: var(--brand-text);
  padding: 8px 28px 32px;
}

.rich-editor :deep(.w-e-text-placeholder) {
  font-style: normal;
  color: #b7bdc9;
  top: 10px;
  left: 28px;
}

.rich-editor :deep(.w-e-bar-item button:hover) {
  background: #f3f0e6;
}
</style>
