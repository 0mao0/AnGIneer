<template>
  <div class="knowledge-tree">
    <a-tree
      v-if="treeData.length"
      :tree-data="treeData"
      :expanded-keys="expandedKeys"
      :selected-keys="selectedKeys"
      :show-icon="true"
      @expand="onExpand"
      @select="onSelect"
    >
      <template #icon="{ isLeaf, isFolder }">
        <FolderOutlined v-if="isFolder" />
        <FileTextOutlined v-else-if="isLeaf" />
      </template>
      <template #title="{ title, isDoc, id }">
        <span :class="{ 'doc-node': isDoc }">
          {{ title }}
        </span>
      </template>
    </a-tree>
    <a-empty v-else description="暂无文档" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'
import type { TreeProps } from 'ant-design-vue'

interface TreeNode {
  key: string
  title: string
  isLeaf?: boolean
  isFolder?: boolean
  isDoc?: boolean
  children?: TreeNode[]
}

const props = defineProps<{
  libraryId?: string
}>()

const emit = defineEmits<{
  select: [node: TreeNode]
}>()

const treeData = ref<TreeNode[]>([])
const expandedKeys = ref<string[]>([])
const selectedKeys = ref<string[]>([])

const onExpand = (keys: string[]) => {
  expandedKeys.value = keys
}

const onSelect: TreeProps['onSelect'] = (keys, info) => {
  selectedKeys.value = keys as string[]
  if (info.node.isDoc) {
    emit('select', info.node as TreeNode)
  }
}

onMounted(async () => {
  treeData.value = [
    {
      key: 'kb-1',
      title: '海港总体设计规范',
      isFolder: true,
      children: [
        { key: 'kb-1-ch1', title: '1 总则', isLeaf: true, isDoc: true },
        { key: 'kb-1-ch2', title: '2 术语', isLeaf: true, isDoc: true },
        { key: 'kb-1-ch3', title: '3 港址选择', isLeaf: true, isDoc: true },
        { key: 'kb-1-ch4', title: '4 设计基础条件', isLeaf: true, isDoc: true },
        { key: 'kb-1-ch5', title: '5 港口平面', isLeaf: true, isDoc: true },
        { key: 'kb-1-ch6', title: '6 进港航道、锚地', isLeaf: true, isDoc: true }
      ]
    }
  ]
  expandedKeys.value = ['kb-1']
})
</script>

<style lang="less" scoped>
.knowledge-tree {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 4px 0;

  :deep(.ant-tree) {
    background: transparent;
    
    .ant-tree-treenode {
      padding: 2px 8px;
      margin: 0;
    }
    
    .ant-tree-node-content-wrapper {
      padding: 2px 4px;
      border-radius: 4px;
    }
    
    .ant-tree-title {
      font-size: 13px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
  }

  .doc-node {
    color: #1890ff;
    cursor: pointer;
    font-size: 13px;

    &:hover {
      text-decoration: underline;
    }
  }
}
</style>
