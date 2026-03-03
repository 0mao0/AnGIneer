<template>
  <!-- 待开发页面占位组件 - 显示规划中提示 -->
  <div class="placeholder-page">
    <a-result
      status="404"
      title="规划中"
      sub-title="该功能正在开发中，敬请期待"
    >
      <template #icon>
        <div class="placeholder-icon">
          <BuildOutlined />
        </div>
      </template>
    </a-result>
  </div>
</template>

<script setup lang="ts">
import { BuildOutlined } from '@ant-design/icons-vue'

/**
 * 待开发页面占位组件
 * 用于显示正在规划中的功能页面
 */
</script>

<style lang="less" scoped>
.placeholder-page {
  flex: 1;
  width: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--bg-primary, #141414);
  transition: background-color 0.3s ease;

  .placeholder-icon {
    font-size: 72px;
    color: #667eea;
    margin-bottom: 24px;
  }

  // 暗黑模式下文字颜色
  :deep(.ant-result-title),
  :deep(.ant-result-subtitle) {
    color: rgba(255, 255, 255, 0.85);
  }
}
</style>
