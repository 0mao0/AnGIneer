<template>
  <div class="knowledge-workspace" :class="appClass">
    <!-- 总览（全库一览 / 新建 / 换组 / 删除） -->
    <div v-if="activeView === 'multilib'" class="knowledge-list-view">
      <MultiLibraryManager />
    </div>

    <!-- 详情（原列表） -->
    <div v-else-if="activeView === 'maintenance'" class="knowledge-list-view">
      <KnowledgeStats />
    </div>

    <!-- 夜巡（健康检查） -->
    <div v-else-if="activeView === 'nightly'" class="knowledge-nightly-view">
      <DreamCycleView />
    </div>

    <!-- AI对话（原解析）：兜底支（activeView 无其它匹配时显示），由详情工具条按钮进入 -->
    <KnowledgeParseWorkspace
      v-else
      :api="knowledgeApi"
      :dark="isDark"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 知识库管理 - 视图容器
 * 总览 + 详情 + 夜巡：头部 tab 控制；
 * AI对话（原解析）：头部 tab 已撤（2026-10-06），入口改为详情工具条按钮，
 * 写入同一个 knowledgeView 状态（provide 自 App.vue）。
 */
import { defineAsyncComponent, inject, onMounted, ref, type Ref } from 'vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import KnowledgeStats from '@/components/KnowledgeStats.vue'
import MultiLibraryManager from '@/components/MultiLibraryManager.vue'

/** keep-alive 的 include 按组件名匹配（见 App.vue 的 cachedViews），少这行会静默不缓存 */
defineOptions({ name: 'KnowledgeManage' })

/**
 * 三视图互斥，另两个只有切过去才需要：改异步组件把它们拆出落地块
 * （KnowledgeParseWorkspace 静态拖着 pdf.js / docx-preview / xlsx 一整个预览栈）。
 * 落地后在浏览器空闲时预热完，切视图时不再等待。
 */
const nightlyLoader = () => import('@/views/DreamCycleView.vue')
const aichatLoader = () => import('@/components/KnowledgeParseWorkspace.vue')
const DreamCycleView = defineAsyncComponent(nightlyLoader)
const KnowledgeParseWorkspace = defineAsyncComponent(aichatLoader)

const { appClass, isDark } = useTheme()

/** 视图状态由 App.vue 头部统一持有（provide/inject）；兜底默认与路由缺省一致＝总览 */
const activeView = inject<Ref<'multilib' | 'maintenance' | 'nightly' | 'aichat'>>('knowledgeView') ?? ref<'multilib' | 'maintenance' | 'nightly' | 'aichat'>('multilib')

onMounted(() => {
  // 同 specifier 的 import() 命中同一 chunk 缓存，预热过则切换时秒开
  const prime = () => { void nightlyLoader(); void aichatLoader() }
  if (typeof requestIdleCallback === 'function') requestIdleCallback(prime, { timeout: 5000 })
  else setTimeout(prime, 2000)
})
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  background: var(--bg-primary);
  display: flex;
  flex-direction: column;
}

.knowledge-list-view,
.knowledge-nightly-view {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
