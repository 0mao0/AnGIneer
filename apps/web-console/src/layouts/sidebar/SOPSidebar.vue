<template>
  <div class="sop-sidebar">
    <SOPTree
      :tree-data="treeData"
      v-bind="treeProps"
      @select="handleTreeSelect"
    >
      <template #icon="{ node }">
        <FolderOutlined v-if="node?.isFolder" style="color: #faad14" />
        <ApiOutlined v-else style="color: #1890ff" />
      </template>
    </SOPTree>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'
import { ApiOutlined, FolderOutlined } from '@ant-design/icons-vue'
import { SOPTree, createResourceNodeFromSop, useSopTree, type SOPTreeNode } from '@angineer/docs-ui'
import { useResourceOpen } from '@/composables/useResourceOpen'

const { openResource } = useResourceOpen()
const { treeData, resetToDefaultTree, setSelectedNode } = useSopTree()

const treeProps = {
  showSearch: true,
  searchPlaceholder: '搜索经验流程...',
  showAddRootFolder: false,
  showStatus: false,
  draggable: false,
  allowAddFile: false,
  emptyText: '暂无 SOP'
}

/**
 * 处理经验库树选中，并在点击叶子节点时打开 SOP 详情。
 */
const handleTreeSelect = (_keys: string[], nodes: SOPTreeNode[]) => {
  if (nodes.length === 0) {
    setSelectedNode(null)
    return
  }

  const node = nodes[0]
  setSelectedNode(node)

  if (node.isFolder) {
    return
  }

  const resource = createResourceNodeFromSop(node)
  openResource(resource)
}

onMounted(() => {
  resetToDefaultTree()
})
</script>

<style lang="less" scoped>
.sop-sidebar {
  height: 100%;
  padding: 12px;
  display: flex;
  flex-direction: column;

  :deep(.smart-tree) {
    background: transparent;
  }
}
</style>
