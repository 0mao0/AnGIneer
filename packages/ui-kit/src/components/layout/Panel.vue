<template>
  <!-- 通用面板组件 - 带标题栏和内容区的标准面板 -->
  <div class="panel" :class="{ 'panel-bordered': bordered }">
    <!-- 面板头部 -->
    <div v-if="title || $slots.header" class="panel-header">
      <slot name="header">
        <div class="header-title">
          <component v-if="icon" :is="icon" />
          <span>{{ title }}</span>
        </div>
        <div v-if="$slots.extra" class="header-extra">
          <slot name="extra" />
        </div>
      </slot>
    </div>

    <!-- 面板内容 -->
    <div class="panel-content" :class="contentClass">
      <slot />
    </div>
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue'

/**
 * 通用面板组件
 * 提供统一的面板样式，包含标题栏和内容区
 */
interface Props {
  /** 面板标题 */
  title?: string
  /** 标题图标 */
  icon?: Component
  /** 是否显示边框 */
  bordered?: boolean
  /** 内容区自定义类名 */
  contentClass?: string
}

withDefaults(defineProps<Props>(), {
  bordered: false
})
</script>

<style lang="less" scoped>
.panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--panel-bg);

  &-bordered {
    border: 1px solid var(--border-color);
    border-radius: 4px;
  }

  &-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    height: 44px;
    padding: 0 16px;
    border-bottom: 1px solid var(--border-color);
    background: var(--panel-header-bg);
    flex-shrink: 0;

    .header-title {
      display: flex;
      align-items: center;
      gap: 8px;
      font-weight: 500;
      color: var(--text-primary);

      .anticon {
        color: var(--primary-color);
      }
    }

    .header-extra {
      display: flex;
      align-items: center;
      gap: 8px;
    }
  }

  &-content {
    flex: 1;
    min-height: 0;
    overflow: auto;
    position: relative;
  }
}
</style>
