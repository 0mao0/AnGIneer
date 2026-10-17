<template>
  <SmartTree
    :ref="setSmartTreeRef"
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
    :multiple="multiple"
    :allow-add-file="allowAddFile"
    :allowed-file-types="allowedFileTypes"
    :loading="loading"
    :empty-text="emptyText"
    :default-expanded-keys="defaultExpandedKeys"
    :default-selected-keys="defaultSelectedKeys"
    :expand-selected-path="expandSelectedPath"
    :dark="dark"
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
      <slot name="icon" v-bind="slotProps">
        <FolderOutlined v-if="slotProps.node?.isFolder" style="color: var(--tree-folder-color)" />
        <ApiOutlined v-else style="color: var(--primary-color)" />
      </slot>
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
 * 在 sop-ui 中承接经验库节点类型与基础树组件之间的边界，便于后续扩展经验库默认行为。
 */
import { ref } from 'vue'
import { ApiOutlined, FolderOutlined } from '@ant-design/icons-vue'
import { SmartTree } from '@angineer/smartree'
import type { SmartTreeExposed } from '@angineer/smartree'
import type { SOPTreeNode } from '../types/sop'

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
  multiple?: boolean
  allowAddFile?: boolean
  allowedFileTypes?: string[]
  loading?: boolean
  emptyText?: string
  defaultExpandedKeys?: string[]
  defaultSelectedKeys?: string[]
  /** 转发 SmartTree expandSelectedPath：选中项变化时自动展开其祖先链（只并集），默认关 */
  expandSelectedPath?: boolean
  // 暗色主题（宿主 useTheme().isDark 传入）：SmartTree 暗色样式挂在 dark 属性上，
  // 不传则整段暗色样式失效（2026-10-15 实踩：搜索框旁「新建文件夹」图标 rgba(0,0,0,.45) 全黑）。
  // docs-ui KnowledgeTree / evals-ui EvalDatasetTree 早有此属性和透传，本组件补齐对齐。
  dark?: boolean
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
  'drop-root': [dragNodeKeys: string[]]
}>()

const smartTreeRef = ref<SmartTreeExposed | null>(null)
const setSmartTreeRef = (instance: unknown) => {
  smartTreeRef.value = (instance ?? null) as SmartTreeExposed | null
}

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
