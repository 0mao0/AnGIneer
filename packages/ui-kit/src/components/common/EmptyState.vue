<template>
  <div class="empty-state">
    <a-empty :description="description">
      <template #image>
        <component :is="icon" v-if="icon" style="font-size: 48px; color: var(--text-secondary)" />
      </template>
      <slot />
    </a-empty>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{
  description?: string
  icon?: any
}>(), {
  description: '暂无数据'
})
</script>

<style lang="less" scoped>
.empty-state {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100%;
  min-height: 200px;
}
</style>
