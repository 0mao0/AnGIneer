<template>
  <div class="page-header">
    <div class="page-header-left">
      <h2 class="page-title">
        <slot name="title">{{ title }}</slot>
      </h2>
      <p v-if="description" class="page-desc">{{ description }}</p>
    </div>
    <div v-if="$slots.extra" class="page-header-right">
      <slot name="extra" />
    </div>
  </div>
</template>

<script setup lang="ts">
defineProps<{ title?: string, description?: string }>()
</script>

<style scoped lang="less">
@import '../../styles/variables.less';

.page-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: @spacing-md;
}
.page-title {
  font-size: @font-size-2xl;
  font-weight: @font-weight-semibold;
  color: @text-primary;
  line-height: 1.3;
}
.page-desc {
  font-size: @font-size-sm;
  color: @text-secondary;
  margin-top: @spacing-xs;
}
</style>
