<template>
  <div class="section-card">
    <div v-if="title || $slots.title || $slots.extra" class="section-card-header">
      <div class="section-card-title">
        <slot name="title">{{ title }}</slot>
      </div>
      <div v-if="$slots.extra" class="section-card-extra">
        <slot name="extra" />
      </div>
    </div>
    <div class="section-card-body" :class="{ 'section-card-body--nopad': nopad, 'section-card-body--flush': flush }">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title?: string, nopad?: boolean, flush?: boolean }>(), { nopad: false, flush: false })
</script>

<style scoped lang="less">
.section-card {
  background: var(--table-card-bg, var(--card-bg, #ffffff));
  border-radius: 12px;
  border: 1px solid var(--table-border-color, var(--border-color, rgba(0, 0, 0, 0.06)));
  box-shadow: var(--table-shadow-sm, var(--shadow-sm, 0 1px 2px rgba(0, 0, 0, 0.06)));
  transition: box-shadow 200ms ease;
  &:hover { box-shadow: var(--table-shadow-md, var(--shadow-md, 0 4px 12px rgba(0, 0, 0, 0.08))); }
}
.section-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 20px 24px;
  border-bottom: 1px solid var(--table-divider-color, var(--divider-color, rgba(0, 0, 0, 0.08)));
}
.section-card-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--table-text-primary, var(--text-primary, rgba(0, 0, 0, 0.85)));
}
.section-card-body {
  padding: 24px;
  &--nopad { padding: 0; }
  // 列表/紧凑场景：顶部贴边，消除标题与列表首项的视觉空隙
  &--flush { padding-top: 0; }
}
</style>
