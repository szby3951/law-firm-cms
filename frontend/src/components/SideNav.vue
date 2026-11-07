<template>
  <div class="side-nav">
    <div class="brand-area" @click="goHome">
      <BrandLogo :compact="collapsed" small />
    </div>

    <el-scrollbar class="menu-scroll">
      <el-menu
        :default-active="activePath"
        :collapse="collapsed"
        :collapse-transition="false"
        router
        class="menu"
        @select="emit('select')"
      >
        <el-menu-item v-for="m in menus" :key="m.path" :index="m.path">
          <el-icon><component :is="m.icon" /></el-icon>
          <template #title>{{ m.label }}</template>
        </el-menu-item>
      </el-menu>
    </el-scrollbar>

    <div v-if="showCollapse" class="aside-foot" @click="emit('toggle')">
      <el-icon><component :is="collapsed ? 'Expand' : 'Fold'" /></el-icon>
      <span v-if="!collapsed">收起导航</span>
    </div>
  </div>
</template>

<script setup>
import { useRouter } from 'vue-router'
import BrandLogo from '@/components/BrandLogo.vue'

const props = defineProps({
  menus: { type: Array, required: true }, // [{ path, label, icon }]
  activePath: { type: String, default: '' },
  homePath: { type: String, default: '/' },
  collapsed: { type: Boolean, default: false },
  showCollapse: { type: Boolean, default: false },
})

const emit = defineEmits(['select', 'toggle'])
const router = useRouter()

function goHome() {
  router.push(props.homePath)
  emit('select')
}
</script>

<style scoped>
.side-nav {
  height: 100%;
  display: flex;
  flex-direction: column;
  background: linear-gradient(180deg, var(--brand-navy) 0%, var(--brand-navy-deep) 100%);
  overflow: hidden;
}

.brand-area {
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 13px;
  cursor: pointer;
  border-bottom: 1px solid rgba(255, 255, 255, 0.07);
  flex-shrink: 0;
}

.menu-scroll {
  flex: 1;
}

.menu {
  border-right: none;
  background: transparent;
  padding: 12px 8px;
  --el-menu-text-color: rgba(255, 255, 255, 0.62);
  --el-menu-hover-bg-color: rgba(255, 255, 255, 0.06);
  --el-menu-active-color: var(--brand-gold-light);
  --el-menu-item-height: 46px;
}

.menu :deep(.el-menu-item) {
  border-radius: 8px;
  margin-bottom: 4px;
  font-size: 14px;
}

.menu :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(201, 165, 92, 0.18), rgba(201, 165, 92, 0.04));
  font-weight: 500;
  position: relative;
}

.menu :deep(.el-menu-item.is-active)::before {
  content: '';
  position: absolute;
  left: 0;
  top: 10px;
  bottom: 10px;
  width: 3px;
  border-radius: 2px;
  background: var(--brand-gold);
}

.aside-foot {
  height: 46px;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 22px;
  color: rgba(255, 255, 255, 0.45);
  font-size: 13px;
  cursor: pointer;
  border-top: 1px solid rgba(255, 255, 255, 0.07);
  flex-shrink: 0;
}

.aside-foot:hover {
  color: var(--brand-gold-light);
}

/* 手机抽屉里菜单项放大一点，方便触控 */
@media (max-width: 768px) {
  .menu {
    padding: 10px 8px;
    --el-menu-item-height: 50px;
  }

  .menu :deep(.el-menu-item) {
    font-size: 15px;
  }
}
</style>
