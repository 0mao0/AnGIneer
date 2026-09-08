<template>
  <div class="knowledge-workspace" :class="appClass">
    <!-- 日常维护（原列表） -->
    <div v-if="activeView === 'maintenance'" class="knowledge-list-view">
      <KnowledgeStats />
    </div>

    <!-- 夜间维护（健康检查） -->
    <div v-else-if="activeView === 'nightly'" class="knowledge-nightly-view">
      <DreamCycleView />
    </div>

    <!-- AI对话（原解析） -->
    <KnowledgeParseWorkspace
      v-else
      :api="knowledgeApi"
      :dark="isDark"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * 知识库管理 - 三视图
 * 日常维护 + 夜间维护 + AI对话，通过 App.vue 头部统一控制
 */
import { inject, ref, type Ref } from 'vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import KnowledgeStats from '@/components/KnowledgeStats.vue'
import KnowledgeParseWorkspace from '@/components/KnowledgeParseWorkspace.vue'
import DreamCycleView from '@/views/DreamCycleView.vue'

const { appClass, isDark } = useTheme()

/** 视图状态由 App.vue 头部统一持有（provide/inject） */
const activeView = inject<Ref<'maintenance' | 'nightly' | 'aichat'>>('knowledgeView') ?? ref<'maintenance' | 'nightly' | 'aichat'>('maintenance')
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
