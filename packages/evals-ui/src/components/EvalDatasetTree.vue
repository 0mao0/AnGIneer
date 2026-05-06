<template>
  <SmartTree
    ref="smartTreeRef"
    :tree-data="treeData"
    :show-search="true"
    :show-add-root-folder="true"
    add-root-folder-title="新建测试集"
    :show-icon="true"
    :show-status="false"
    :draggable="false"
    :default-expanded-keys="defaultExpandedKeys"
    :default-selected-keys="defaultSelectedKeys"
    empty-text="暂无测试集"
    search-placeholder="搜索测试集..."
    @select="onSelect"
    @rename="(node) => emit('rename', node as EvalTreeNode)"
    @delete="(node) => emit('delete', node as EvalTreeNode)"
    @view="(node) => emit('view', node as EvalTreeNode)"
    @add-folder="(node) => emit('add-folder', node as EvalTreeNode | null)"
    @add-file="(node) => emit('add-file', node as EvalTreeNode)"
  >
    <template #icon="{ node }">
      <FolderOutlined v-if="node.isFolder" style="color: var(--tree-folder-color)" />
      <FileTextOutlined v-else style="color: var(--text-secondary)" />
    </template>
    <template #title="{ node }">
      <span>{{ node.title }}</span>
      <span v-if="!node.isFolder && node.questionCount" class="eval-node-count">
        {{ node.questionCount }}
      </span>
    </template>
    <template #actions="{ node }">
      <template v-if="isGroupNode(node)">
        <EditOutlined class="action-icon" title="重命名" @click.stop="emit('rename', node)" />
        <FileAddOutlined class="action-icon" title="添加测试集" @click.stop="emit('add-file', node)" />
        <FolderAddOutlined class="action-icon" title="添加子文件夹" @click.stop="emit('add-folder', node)" />
        <DeleteOutlined class="action-icon delete" title="删除" @click.stop="emit('delete', node)" />
      </template>
      <template v-else-if="node.isFolder">
        <EditOutlined class="action-icon" title="重命名" @click.stop="emit('rename', node)" />
        <FileAddOutlined class="action-icon" title="添加测试集" @click.stop="emit('add-file', node)" />
        <FolderAddOutlined class="action-icon" title="添加子文件夹" @click.stop="emit('add-folder', node)" />
        <DeleteOutlined class="action-icon delete" title="删除" @click.stop="emit('delete', node)" />
      </template>
      <template v-else>
        <EditOutlined class="action-icon" title="重命名" @click.stop="emit('rename', node)" />
        <EyeOutlined class="action-icon" title="查看详情" @click.stop="emit('view', node)" />
        <DeleteOutlined class="action-icon delete" title="删除" @click.stop="emit('delete', node)" />
      </template>
    </template>
  </SmartTree>
</template>

<script lang="ts">
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDatasetCategory } from '../types/eval'
import { isGroupNode, getCategoryFromGroupKey } from '../composables/useEvalDatasetTree'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

export { isGroupNode, getCategoryFromGroupKey }
</script>

<script setup lang="ts">
import { ref } from 'vue'
import {
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  FileTextOutlined,
  FolderAddOutlined,
  FolderOutlined,
} from '@ant-design/icons-vue'
import { SmartTree } from '@angineer/ui-kit'

defineProps<{
  treeData: SmartTreeNode[]
  defaultExpandedKeys?: string[]
  defaultSelectedKeys?: string[]
}>()

const emit = defineEmits<{
  select: [datasetId: string]
  rename: [node: EvalTreeNode]
  delete: [node: EvalTreeNode]
  view: [node: EvalTreeNode]
  'add-folder': [parentNode: EvalTreeNode | null]
  'add-file': [parentNode: EvalTreeNode]
}>()

const smartTreeRef = ref<InstanceType<typeof SmartTree> | null>(null)

const onSelect = (keys: string[], _nodes: SmartTreeNode[]) => {
  if (keys.length > 0) {
    const key = keys[0]
    if (!key.startsWith('group-')) {
      emit('select', key)
    }
  }
}

defineExpose({
  get expandedKeys() {
    return smartTreeRef.value?.expandedKeys || []
  },
  set expandedKeys(value: string[]) {
    if (smartTreeRef.value) {
      smartTreeRef.value.expandedKeys = value
    }
  },
  get selectedKeys() {
    return smartTreeRef.value?.selectedKeys || []
  },
  set selectedKeys(value: string[]) {
    if (smartTreeRef.value) {
      smartTreeRef.value.selectedKeys = value
    }
  },
  getCategoryFromGroupKey,
})
</script>

<style lang="less" scoped>
.eval-node-count {
  font-size: 12px;
  color: var(--text-secondary, rgba(0, 0, 0, 0.45));
  background: var(--bg-tertiary);
  padding: 0 6px;
  border-radius: 10px;
  margin-left: 4px;
}
</style>
