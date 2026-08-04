<template>
  <div class="knowledge-workspace" :class="appClass">
    <!-- ???? -->
    <div v-if="activeView === 'list'" class="knowledge-list-view">
      <KnowledgeStats
        :active-view="activeView"
        @update:active-view="activeView = $event"
      />
    </div>

    <!-- ??????????????? KnowledgeParseWorkspace? -->
    <KnowledgeParseWorkspace
      v-else
      :api="knowledgeApi"
      :active-view="activeView"
      :dark="isDark"
      @update:active-view="activeView = $event"
    />
  </div>
</template>

<script setup lang="ts">
/**
 * ?????? - ???
 * ???? + ??????????????????? KnowledgeParseWorkspace ??
 * ?? Vue3 ???? KnowledgeApiPort ?????????
 */
import { ref } from 'vue'
import { useTheme } from '@angineer/ui-kit'
import { knowledgeApi } from '@/api/knowledge'
import KnowledgeStats from '@/components/KnowledgeStats.vue'
import KnowledgeParseWorkspace from '@/components/KnowledgeParseWorkspace.vue'

const { appClass, isDark } = useTheme()

const activeView = ref<'list' | 'parse'>('list')
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
