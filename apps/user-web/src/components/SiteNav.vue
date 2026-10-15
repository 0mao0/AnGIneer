<template>
  <nav class="site-nav" aria-label="页面导航">
    <RouterLink
      v-for="entry in entries"
      :key="entry.path"
      :to="entry.path"
      class="site-nav-link"
      :class="{ active: isActive(entry) }"
    >
      {{ entry.label }}
    </RouterLink>
  </nav>
</template>

<script setup lang="ts">
/** 全站页签导航（问答 | 测试集 | 经验库）：ChatTopBar 与 PublicTopBar 共用。
 *  catch-all 仍回聊天：这里只加显式入口，不改路由兜底。 */
import { useRoute } from 'vue-router'
import { RouterLink } from 'vue-router'

const entries = [
  { path: '/', label: '问答', exact: true },
  { path: '/evals', label: '测试集', exact: false },
  { path: '/sops', label: '经验库', exact: false },
]

const route = useRoute()

function isActive(entry: { path: string; exact: boolean }): boolean {
  return entry.exact ? route.path === '/' : route.path.startsWith(entry.path)
}
</script>

<style lang="less" scoped>
.site-nav {
  display: flex;
  align-items: center;
  gap: 2px;
  margin-inline-start: 24px;
  /* 紧贴品牌左置，右侧动作区自然推远（三元素 space-between 下 SiteNav 会漂中间） */
  margin-right: auto;
  height: 100%;

  .site-nav-link {
    display: inline-flex;
    align-items: center;
    height: 100%;
    padding: 0 10px;
    font-size: 14px;
    color: var(--text-secondary);
    text-decoration: none;
    border-bottom: 2px solid transparent;
    transition: color 0.2s ease, border-color 0.2s ease;

    &:hover {
      color: var(--text-primary);
    }

    &.active {
      color: var(--text-primary);
      font-weight: 600;
      border-bottom-color: var(--primary-color);
    }
  }
}
</style>
