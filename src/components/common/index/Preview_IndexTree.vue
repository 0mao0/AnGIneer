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
        :selected-node-ids="selectedNodeIds"
        :source-file-path="sourceFilePath"
        @toggle="onToggle"
        @select="onSelect"
        @edit="onEdit"
        @toggle-check="onToggleCheck"
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
  selectedNodeIds?: Set<string>
  sourceFilePath?: string
}

const props = defineProps<Props>()

const emit = defineEmits<Pick<PreviewIndexInteractionEventMap, 'toggle' | 'select'> & {
  edit: [id: string]
  'toggle-check': [id: string]
}>()
const treeContainerRef = ref<HTMLElement | null>(null)

const onToggle = (id: string) => {
  emit('toggle', id)
}

const onSelect = (id: string) => {
  emit('select', id)
}

/* 转发节点编辑事件给外层工作区。 */
const onEdit = (id: string) => {
  emit('edit', id)
}

const onToggleCheck = (id: string) => {
  emit('toggle-check', id)
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
