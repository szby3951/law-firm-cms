<template>
  <div class="brand-logo" :class="{ compact, small }">
    <div class="seal">
      <svg viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg">
        <!-- 天平：律所行业标识 -->
        <path
          d="M20 8v24M8 14h24M12 14l-4 8h8l-4-8zm16 0l-4 8h8l-4-8zM13 32h14"
          stroke="currentColor"
          stroke-width="2"
          stroke-linecap="round"
          stroke-linejoin="round"
        />
      </svg>
    </div>
    <div v-if="!compact" class="brand-text">
      <div class="name">律所客户智能管理系统</div>
      <div class="en">LAW FIRM INTELLIGENT CMS</div>
    </div>
  </div>
</template>

<script setup>
defineProps({
  compact: { type: Boolean, default: false },
  small: { type: Boolean, default: false },
})
</script>

<style scoped>
.brand-logo {
  display: flex;
  align-items: center;
  gap: 12px;
  color: var(--brand-gold);
}

.seal {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--brand-gold) 0%, var(--brand-gold-deep) 100%);
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.seal svg {
  width: 24px;
  height: 24px;
}

.brand-text {
  min-width: 0;
}

.brand-text .name {
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.5px;
  line-height: 1.3;
  color: inherit;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.brand-text .en {
  font-size: 9px;
  letter-spacing: 1px;
  opacity: 0.55;
  margin-top: 3px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* small 变体：侧边栏等窄空间使用 */
.brand-logo.small .seal {
  width: 34px;
  height: 34px;
}

.brand-logo.small .brand-text .name {
  font-size: 13px;
  letter-spacing: 0;
}

.brand-logo.small .brand-text .en {
  display: none;
}
</style>
