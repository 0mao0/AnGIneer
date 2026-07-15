<template>
  <SmartTree
    ref="smartTreeRef"
    :tree-data="treeData"
    :show-search="showSearch"
    :search-placeholder="searchPlaceholder"
    :highlight-search="highlightSearch"
    :show-add-root-folder="showAddRootFolder"
    :add-root-folder-text="addRootFolderText"
    :add-root-folder-title="addRootFolderTitle"
    :show-icon="showIcon"
    :show-status="showStatus"
    :show-line="showLine"
    :draggable="draggable"
    :allow-add-file="allowAddFile"
    :allowed-file-types="allowedFileTypes"
    :loading="loading"
    :empty-text="emptyText"
    :default-expanded-keys="defaultExpandedKeys"
    :default-selected-keys="defaultSelectedKeys"
    @select="(keys, nodes) => emit('select', keys, nodes as EvalTreeNode[])"
    @rename="(node) => emit('rename', node as EvalTreeNode)"
    @add-folder="(node) => emit('add-folder', node as EvalTreeNode | null)"
    @add-file="(node) => emit('add-file', node as EvalTreeNode)"
    @delete="(node) => emit('delete', node as EvalTreeNode)"
    @view="(node) => emit('view', node as EvalTreeNode)"
    @drop="(info) => emit('drop', info)"
    @search="(text) => emit('search', text)"
    @file-drop="(files, targetFolder) => emit('file-drop', files, targetFolder as EvalTreeNode | null)"
    @drop-invalid="(reason) => emit('drop-invalid', reason)"
    @drop-root="(dragNodeKey) => emit('drop-root', dragNodeKey)"
  >
    <template #icon="slotProps">
      <slot name="icon" v-bind="slotProps">
        <FolderOutlined v-if="slotProps.node?.isFolder" style="color: var(--tree-folder-color)" />
        <FileTextOutlined v-else style="color: var(--text-secondary)" />
      </slot>
    </template>
    <template #title="slotProps">
      <slot name="title" v-bind="slotProps">
        <span>{{ slotProps.node?.title }}</span>
        <span v-if="slotProps.node && !slotProps.node.isFolder && slotProps.node.questionCount" class="eval-node-count">
          {{ slotProps.node.questionCount }}
        </span>
      </slot>
    </template>
    <template #status="slotProps">
      <slot name="status" v-bind="slotProps" />
    </template>
    <template #actions="slotProps">
      <slot name="actions" v-bind="slotProps" />
    </template>
    <template #empty="slotProps">
      <slot name="empty" v-bind="slotProps" />
    </template>
  </SmartTree>
</template>

<script lang="ts">
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDatasetCategory } from '../types/eval'
import { isCategoryFolder, isPersistedFolder } from '../composables/useEvalDatasetTree'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

export interface EvalDatasetTreeProps {
  treeData: EvalTreeNode[]
  showSearch?: boolean
  searchPlaceholder?: string
  highlightSearch?: boolean
  showAddRootFolder?: boolean
  addRootFolderText?: string
  addRootFolderTitle?: string
  showIcon?: boolean
  showStatus?: boolean
  showLine?: boolean
  draggable?: boolean
  allowAddFile?: boolean
  allowedFileTypes?: string[]
  loading?: boolean
  emptyText?: string
  defaultExpandedKeys?: string[]
  defaultSelectedKeys?: string[]
}

export { isCategoryFolder, isPersistedFolder }
</script>

<script setup lang="ts">
/**
 * 评测数据集树语义组件。
 * 在 evals-ui 中承接评测节点类型与基础树组件之间的边界，便于后续扩展评测域默认行为。
 */
import { ref } from 'vue'
import { SmartTree } from '@angineer/ui-kit'
import type { DropEvent } from '@angineer/ui-kit'
import { FolderOutlined, FileTextOutlined } from '@ant-design/icons-vue'

defineProps<EvalDatasetTreeProps>()

const emit = defineEmits<{
  select: [keys: string[], nodes: EvalTreeNode[]]
  rename: [node: EvalTreeNode]
  'add-folder': [node: EvalTreeNode | null]
  'add-file': [node: EvalTreeNode]
  delete: [node: EvalTreeNode]
  view: [node: EvalTreeNode]
  drop: [event: DropEvent]
  search: [text: string]
  'file-drop': [files: File[], targetFolder: EvalTreeNode | null]
  'drop-invalid': [reason: string]
  'drop-root': [dragNodeKeys: string[]]
}>()

const smartTreeRef = ref<InstanceType<typeof SmartTree> | null>(null)

/** 展开所有评测节点。 */
const expandAll = () => {
  smartTreeRef.value?.expandAll()
}

/** 收起所有评测节点。 */
const collapseAll = () => {
  smartTreeRef.value?.collapseAll()
}

/** 获取当前选中的评测节点。 */
const getSelectedNodes = (): EvalTreeNode[] => {
  return (smartTreeRef.value?.getSelectedNodes() || []) as EvalTreeNode[]
}

/** 校验上传文件类型。 */
const validateFileType = (file: File): boolean => {
  return smartTreeRef.value?.validateFileType(file) ?? false
}

/** 获取允许上传的文件类型描述。 */
const getAllowedFileTypesDesc = (): string => {
  return smartTreeRef.value?.getAllowedFileTypesDesc() || '所有文件'
}

defineExpose({
  expandAll,
  collapseAll,
  getSelectedNodes,
  validateFileType,
  getAllowedFileTypesDesc,
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
})
</script>

<style lang="less" scoped>
.eval-node-count {
  font-size: 12px;
  color: var(--text-secondary);
  background: var(--bg-tertiary);
  padding: 0 6px;
  border-radius: 10px;
  margin-left: 4px;
}
</style>
