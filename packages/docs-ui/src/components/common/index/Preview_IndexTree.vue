<template>
  <div ref="treeContainerRef" class="doc-blocks-tree">
    <div v-if="loading" class="tree-loading">
      <a-spin size="small" />
      <span>加载中...</span>
    </div>
    <a-empty v-else-if="!roots.length" description="暂无结构数据" />
    <ul v-else class="tree-root">
      <DocBlocksTreeNode
        v-for="nodeId in roots"
        :key="nodeId"
        :node-id="nodeId"
        :node-map="nodeMap"
        :children-map="childrenMap"
        :expanded-ids="expandedNodeIds"
        :active-node-id="activeNodeId"
        :source-file-path="sourceFilePath"
        @toggle="onToggle"
        @select="onSelect"
      />
    </ul>
  </div>
</template>

<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import type { DocBlockNode, PreviewIndexInteractionEventMap } from '../../../types/knowledge'
import DocBlocksTreeNode from './DocBlocksTreeNode.vue'

interface Props {
  loading?: boolean
  nodeMap: Map<string, DocBlockNode>
  childrenMap: Map<string, string[]>
  roots: string[]
  expandedNodeIds: Set<string>
  activeNodeId: string | null
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<Pick<PreviewIndexInteractionEventMap, 'toggle' | 'select'>>()
const treeContainerRef = ref<HTMLElement | null>(null)

const onToggle = (id: string) => {
  emit('toggle', id)
}

const onSelect = (id: string) => {
  emit('select', id)
}

/**
 * 将当前激活节点滚动到树视图中间位置。
 */
const scrollActiveNodeIntoView = () => {
  if (!props.activeNodeId) return
  nextTick(() => {
    const container = treeContainerRef.value
    if (!container) return
    const target = container.querySelector(`[data-tree-node-id="${CSS.escape(props.activeNodeId || '')}"]`) as HTMLElement | null
    if (!target) return
    target.scrollIntoView({ behavior: 'smooth', block: 'center' })
  })
}

watch(() => props.activeNodeId, () => {
  scrollActiveNodeIntoView()
})

watch(() => props.expandedNodeIds, () => {
  scrollActiveNodeIntoView()
}, { deep: true })
</script>

<style lang="less" scoped>
.doc-blocks-tree {
  height: 100%;
  overflow-y: auto;
  font-size: 13px;
}

.tree-loading {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 24px;
  color: var(--dp-sub-text, #6b7280);
}

.tree-root {
  list-style: none;
  margin: 0;
  padding: 0;
}
</style>
