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
@import '../../styles/variables.less';

.section-card {
  background: @card-bg;
  border-radius: @radius-lg;
  border: 1px solid @border-color;
  box-shadow: @shadow-sm;
  transition: box-shadow @transition-base;
  &:hover { box-shadow: @shadow-md; }
}
.section-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: @spacing-lg @spacing-xl;
  border-bottom: 1px solid @divider-color;
}
.section-card-title {
  font-size: @font-size-lg;
  font-weight: @font-weight-semibold;
  color: @text-primary;
}
.section-card-body {
  padding: @spacing-xl;
  &--nopad { padding: 0; }
  // 列表/紧凑场景：顶部贴边，消除标题与列表首项的视觉空隙
  &--flush { padding-top: 0; }
}
</style>
