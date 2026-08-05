<template>
  <div class="knowledge-workspace" :class="appClass">
    <!-- ???? -->
    <div v-if="activeView === 'list'" class="knowledge-list-view">
      <KnowledgeStats
      />
    </div>

    <!-- ??????????????? KnowledgeParseWorkspace? -->
    <KnowledgeParseWorkspace
      v-else
      :api="knowledgeApi"
      :dark="isDark"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * ?????? - ???
 * ???? + ??????????????????? KnowledgeParseWorkspace ??
 * ?? Vue3 ???? KnowledgeApiPort ?????????
 */
import { inject, ref, type Ref } from 'vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import KnowledgeStats from '@/components/KnowledgeStats.vue'
import KnowledgeParseWorkspace from '@/components/KnowledgeParseWorkspace.vue'

const { appClass, isDark } = useTheme()

/** 视图状态由 App.vue 头部统一持有（provide/inject） */
const activeView = inject<Ref<'list' | 'parse'>>('knowledgeView') ?? ref<'list' | 'parse'>('list')
</script>

<style lang="less" scoped>
.knowledge-workspace {
  height: 100%;
  background: var(--bg-primary);
  display: flex;
  flex-direction: column;
}

.knowledge-list-view {
  flex: 1;
  min-height: 0;
  overflow: hidden;
}
</style>
