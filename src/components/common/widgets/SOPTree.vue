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
    @select="(keys, nodes) => emit('select', keys, nodes as SOPTreeNode[])"
    @rename="(node) => emit('rename', node as SOPTreeNode)"
    @add-folder="(node) => emit('add-folder', node as SOPTreeNode | null)"
    @add-file="(node) => emit('add-file', node as SOPTreeNode)"
    @delete="(node) => emit('delete', node as SOPTreeNode)"
    @view="(node) => emit('view', node as SOPTreeNode)"
    @drop="(info) => emit('drop', info)"
    @search="(text) => emit('search', text)"
    @file-drop="(files, targetFolder) => emit('file-drop', files, targetFolder as SOPTreeNode | null)"
    @drop-invalid="(reason) => emit('drop-invalid', reason)"
    @drop-root="(dragNodeKey) => emit('drop-root', dragNodeKey)"
  >
    <template #icon="slotProps">
      <slot name="icon" v-bind="slotProps" />
    </template>
    <template #title="slotProps">
      <slot name="title" v-bind="slotProps" />
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

<script setup lang="ts">
/**
 * 经验库树语义组件。
 * 在 docs-ui 中承接经验库节点类型与基础树组件之间的边界，便于后续扩展经验库默认行为。
 */
import { ref } from 'vue'
import { SmartTree } from '@angineer/ui-kit'
import type { SOPTreeNode } from '../../../types/tree'

export type { SOPTreeNode }

interface Props {
  treeData: SOPTreeNode[]
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

defineProps<Props>()

const emit = defineEmits<{
  select: [keys: string[], nodes: SOPTreeNode[]]
  rename: [node: SOPTreeNode]
  'add-folder': [node: SOPTreeNode | null]
  'add-file': [node: SOPTreeNode]
  delete: [node: SOPTreeNode]
  view: [node: SOPTreeNode]
  drop: [info: any]
  search: [text: string]
  'file-drop': [files: File[], targetFolder: SOPTreeNode | null]
  'drop-invalid': [reason: string]
  'drop-root': [dragNodeKey: string]
}>()

const smartTreeRef = ref<InstanceType<typeof SmartTree> | null>(null)

/**
 * 展开所有经验库节点。
 */
const expandAll = () => {
  smartTreeRef.value?.expandAll()
}

/**
 * 收起所有经验库节点。
 */
const collapseAll = () => {
  smartTreeRef.value?.collapseAll()
}

/**
 * 获取当前选中的经验库节点。
 */
const getSelectedNodes = (): SOPTreeNode[] => {
  return (smartTreeRef.value?.getSelectedNodes() || []) as SOPTreeNode[]
}

/**
 * 校验上传文件类型。
 */
const validateFileType = (file: File): boolean => {
  return smartTreeRef.value?.validateFileType(file) ?? false
}

/**
 * 获取允许上传的文件类型描述。
 */
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
  }
})
</script>
