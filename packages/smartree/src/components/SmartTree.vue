<template>
  <div
    class="smart-tree"
    :class="{ 'dark-mode': dark }"
    @dragover="onFileDragOver"
    @dragleave="onFileDragLeave"
    @drop="onFileDrop"
    @dragend="onContainerDragEnd"
  >
    <div v-if="showSearch || showAddRootFolder" class="tree-search">
      <a-input
        v-if="showSearch"
        v-model:value="searchText"
        :placeholder="searchPlaceholder"
        allow-clear
        @press-enter="onSearch"
        @change="onSearch"
      >
        <template #prefix>
          <SearchOutlined class="search-icon" />
        </template>
      </a-input>
      <button
        v-if="showAddRootFolder"
        type="button"
        class="search-add-btn"
        :title="addRootFolderTitle"
        :aria-label="addRootFolderTitle"
        @click="$emit('add-folder', null)"
      >
        <FolderAddOutlined />
      </button>
    </div>

    <div class="tree-content">
      <a-tree
        v-if="filteredTreeData.length"
        v-model:selectedKeys="selectedKeys"
        v-model:expandedKeys="expandedKeys"
        :tree-data="filteredTreeData"
        :show-icon="showIcon"
        :block-node="true"
        :draggable="draggable"
        :show-line="showLine"
        :multiple="multiple"
        :virtual="virtual"
        :height="height"
        @select="onSelect"
        @drop="onDrop"
        @dragstart="onNodeDragStart"
        @dragend="onNodeDragEnd"
      >
        <template #title="{ title, key, dataRef: node }">
          <template v-if="node">
            <slot name="node" :node="node">
              <div
                class="tree-node-default"
                :class="{
                  'is-folder': node.isFolder,
                  'is-leaf': !node.isFolder,
                  [`level-${node.level || 0}`]: true
                }"
                @dblclick.stop="onNodeDblClick(node)"
              >
                <span v-if="showIcon" class="node-icon">
                  <slot name="icon" :node="node">
                    <FolderOutlined v-if="node.isFolder" />
                    <component
                      v-else
                      :is="getFileIconComponent(node.title || '')"
                      :style="{ color: getFileIconColor(node.title || '') }"
                    />
                  </slot>
                </span>

                <span class="node-title" :title="title">
                  <slot name="title" :node="node">
                    <span v-if="searchText && highlightSearch" v-html="highlightText(title, searchText)" />
                    <span v-else>{{ title }}</span>
                  </slot>
                </span>

                <span v-if="!node.isFolder && node.status && showStatus" class="node-status">
                  <slot name="status" :node="node">
                    <a-tag :color="getStatusColor(node.status || '')" size="small">
                      {{ getStatusText(node.status || '') }}
                    </a-tag>
                  </slot>
                </span>

                <span class="node-actions" @click.stop>
                  <slot name="actions" :node="node">
                    <template v-if="node.isFolder">
                      <button
                        type="button"
                        class="action-btn"
                        :aria-label="actionLabel('rename')"
                        :title="actionLabel('rename')"
                        @click.stop="onRename(key)"
                      >
                        <EditOutlined />
                      </button>
                      <button
                        type="button"
                        class="action-btn"
                        :aria-label="actionLabel('addSubFolder')"
                        :title="actionLabel('addSubFolder')"
                        @click.stop="onAddFolder(key)"
                      >
                        <FolderAddOutlined />
                      </button>
                      <button
                        v-if="allowAddFile"
                        type="button"
                        class="action-btn"
                        :aria-label="actionLabel('addFile')"
                        :title="actionLabel('addFile')"
                        @click.stop="onAddFile(key)"
                      >
                        <FileAddOutlined />
                      </button>
                      <button
                        v-if="allowBatchDelete"
                        type="button"
                        class="action-btn delete"
                        :aria-label="actionLabel('batchDelete')"
                        :title="actionLabel('batchDelete')"
                        @click.stop="onBatchDelete(key)"
                      >
                        <CheckSquareOutlined />
                      </button>
                      <button
                        type="button"
                        class="action-btn delete"
                        :aria-label="actionLabel('delete')"
                        :title="actionLabel('delete')"
                        @click.stop="onDelete(key)"
                      >
                        <DeleteOutlined />
                      </button>
                    </template>
                    <template v-else>
                      <button
                        type="button"
                        class="action-btn"
                        :aria-label="actionLabel('rename')"
                        :title="actionLabel('rename')"
                        @click.stop="onRename(key)"
                      >
                        <EditOutlined />
                      </button>
                      <button
                        type="button"
                        class="action-btn"
                        :aria-label="actionLabel('view')"
                        :title="actionLabel('view')"
                        @click.stop="onView(key)"
                      >
                        <EyeOutlined />
                      </button>
                      <button
                        type="button"
                        class="action-btn delete"
                        :aria-label="actionLabel('delete')"
                        :title="actionLabel('delete')"
                        @click.stop="onDelete(key)"
                      >
                        <DeleteOutlined />
                      </button>
                    </template>
                  </slot>
                </span>
              </div>
            </slot>
          </template>
          <template v-else>
            <span>{{ title }}</span>
          </template>
        </template>
      </a-tree>

      <div
        v-if="draggable && draggingNodeKeys.length"
        class="root-drop-zone"
        @dragenter.prevent="onRootDragEnter"
        @dragover.prevent="onRootDragOver"
        @dragleave="onRootDragLeave"
        @drop.prevent="onRootDrop"
      >
        {{ rootDropText }}
      </div>

      <div v-if="!filteredTreeData.length && !loading" class="tree-empty">
        <slot name="empty">
          <a-empty :description="searchText ? noSearchResultText : emptyText" />
          <a-button
            v-if="showAddRootFolder && !searchText"
            type="primary"
            size="small"
            class="add-root-btn"
            @click="$emit('add-folder', null)"
          >
            <template #icon><FolderAddOutlined /></template>
            {{ addRootFolderText }}
          </a-button>
        </slot>
      </div>

      <div v-if="loading" class="tree-loading">
        <a-spin size="small" />
      </div>

      <div v-if="isDraggingFile" class="file-drop-hint">
        <CloudUploadOutlined />
        <span>{{ fileDropHintPrefix }} {{ dragOverKey && getOriginalNode(dragOverKey) ? getOriginalNode(dragOverKey)?.title : '根目录' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts" generic="T extends SmartTreeNode">
/**
 * 通用智能树组件。
 * 支持搜索、拖拽、自定义渲染，适用于知识树、经验树等多种场景。
 */
import { computed, ref, shallowRef, watch, type Component } from 'vue'
import type { TreeProps } from 'ant-design-vue'
import {
  CloudUploadOutlined,
  DeleteOutlined,
  EditOutlined,
  EyeOutlined,
  FileAddOutlined,
  FileExcelOutlined,
  FileImageOutlined,
  FileMarkdownOutlined,
  FileOutlined,
  FilePdfOutlined,
  FilePptOutlined,
  FileTextOutlined,
  FileWordOutlined,
  FileZipOutlined,
  CheckSquareOutlined,
  FolderAddOutlined,
  FolderOutlined,
  SearchOutlined
} from '@ant-design/icons-vue'
import type { SmartTreeNode, DropEvent } from '../types/tree'

import {
  highlightText,
  getFileIconType,
  getFileIconColor,
  getStatusColor,
  getStatusText,
  filterTree,
  getExpandedKeysForSearch,
  cloneTree
} from '../utils/tree'

interface AntTreeDropInfo {
  dragNode: { key: string | number }
  node: { key: string | number; pos?: string; dataRef?: T }
  dragNodesKeys?: (string | number)[]
  dropToGap?: boolean
  dropPosition?: number
}

interface AntTreeDragInfo {
  selectedKeys?: (string | number)[]
  node?: { key?: string | number }
}

interface Props<T extends SmartTreeNode> {
  treeData: T[]
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
  allowBatchDelete?: boolean
  allowedFileTypes?: string[]
  loading?: boolean
  emptyText?: string
  defaultExpandedKeys?: string[]
  defaultSelectedKeys?: string[]
  dark?: boolean
  virtual?: boolean
  height?: number
  rootDropText?: string
  noSearchResultText?: string
  fileDropHintPrefix?: string
  actionLabels?: Partial<Record<'rename' | 'addSubFolder' | 'addFile' | 'view' | 'delete' | 'batchDelete', string>>
  defaultExpandAll?: boolean
}

const props = withDefaults(defineProps<Props<T>>(), {
  showSearch: true,
  searchPlaceholder: '搜索...',
  highlightSearch: true,
  showAddRootFolder: true,
  addRootFolderText: '新增文件夹',
  addRootFolderTitle: '新增一级目录',
  showIcon: true,
  showStatus: true,
  showLine: false,
  draggable: false,
  multiple: false,
  allowAddFile: true,
  allowBatchDelete: true,
  allowedFileTypes: () => ['.pdf'],
  loading: false,
  emptyText: '暂无数据',
  defaultExpandedKeys: () => [],
  defaultSelectedKeys: () => [],
  dark: false,
  virtual: false,
  height: undefined,
  rootDropText: '拖动到此移动到根目录',
  noSearchResultText: '无匹配结果',
  fileDropHintPrefix: '释放上传至',
  actionLabels: () => ({}),
  defaultExpandAll: false
})

const emit = defineEmits<{
  select: [keys: string[], nodes: T[]]
  rename: [node: T]
  'add-folder': [node: T | null]
  'add-file': [node: T]
  delete: [node: T]
  'batch-delete': [node: T]
  view: [node: T]
  drop: [event: DropEvent]
  search: [text: string]
  'file-drop': [files: File[], targetFolder: T | null]
  'drop-invalid': [reason: string]
  'drop-root': [dragNodeKeys: string[]]
}>()

const DEFAULT_ACTION_LABELS: Record<'rename' | 'addSubFolder' | 'addFile' | 'view' | 'delete' | 'batchDelete', string> = {
  rename: '重命名',
  addSubFolder: '添加子文件夹',
  addFile: '添加文件',
  view: '查看',
  delete: '删除',
  batchDelete: '批量删除'
}

const actionLabel = (action: keyof typeof DEFAULT_ACTION_LABELS): string =>
  props.actionLabels?.[action] || DEFAULT_ACTION_LABELS[action]

const searchText = ref('')
const initialExpandedApplied = ref(false)

const collectFolderKeys = (nodes: T[]): string[] => {
  const keys: string[] = []
  const walk = (items: T[]) => {
    for (const node of items) {
      if (node.children && node.children.length > 0) {
        keys.push(node.key)
        walk(node.children as T[])
      }
    }
  }
  walk(nodes)
  return keys
}
const expandedKeys = ref<string[]>(props.defaultExpandedKeys)
const selectedKeys = ref<string[]>(props.defaultSelectedKeys)
const internalTreeData = shallowRef<T[]>([])
const isDraggingFile = ref(false)
const dragOverKey = ref<string | null>(null)
const draggingNodeKeys = ref<string[]>([])

const sourceTreeData = computed(() => {
  if (internalTreeData.value.length === 0 && props.treeData.length > 0) {
    return props.treeData
  }
  return internalTreeData.value
})

const originalNodeMap = computed(() => {
  const map = new Map<string, T>()
  const walk = (nodes: T[]) => {
    for (const node of nodes) {
      map.set(node.key, node)
      if (node.children?.length) {
        walk(node.children as T[])
      }
    }
  }
  walk(props.treeData)
  return map
})

watch(() => props.treeData, (value) => {
  internalTreeData.value = cloneTree(value)
  if (props.defaultExpandAll && !initialExpandedApplied.value && value.length > 0) {
    expandedKeys.value = collectFolderKeys(value)
    initialExpandedApplied.value = true
  }
}, { immediate: true, deep: true })

watch(() => props.defaultExpandedKeys, (value) => {
  if (!initialExpandedApplied.value) {
    expandedKeys.value = value
  }
}, { immediate: true })

watch(() => props.defaultSelectedKeys, (value) => {
  selectedKeys.value = value
}, { immediate: true })

/**
 * 根据搜索词过滤树数据。
 */
const filteredTreeData = computed(() => {
  if (!searchText.value) return sourceTreeData.value
  return filterTree(sourceTreeData.value, searchText.value.toLowerCase())
})

watch(searchText, (value) => {
  if (!value || !value.trim()) return
  const keysToExpand = getExpandedKeysForSearch(props.treeData, value.toLowerCase())
  expandedKeys.value = [...new Set([...expandedKeys.value, ...keysToExpand])]
})

/**
 * 从原始树中读取节点。
 */
const getOriginalNode = (key: string): T | undefined => {
  return originalNodeMap.value.get(key)
}

const onRename = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('rename', node)
}

const onAddFolder = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('add-folder', node)
}

const onAddFile = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('add-file', node)
}

const onView = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('view', node)
}

const onDelete = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('delete', node)
}

const onBatchDelete = (key: string) => {
  const node = getOriginalNode(key)
  if (node) emit('batch-delete', node)
}

const onNodeDblClick = (node: T) => {
  if (!node.isFolder) return
  if (expandedKeys.value.includes(node.key)) {
    expandedKeys.value = expandedKeys.value.filter((key) => key !== node.key)
    return
  }
  expandedKeys.value = [...new Set([...expandedKeys.value, node.key])]
}

const fileIconComponentMap: Record<string, Component> = {
  pdf: FilePdfOutlined,
  word: FileWordOutlined,
  excel: FileExcelOutlined,
  ppt: FilePptOutlined,
  image: FileImageOutlined,
  zip: FileZipOutlined,
  text: FileTextOutlined,
  markdown: FileMarkdownOutlined,
  file: FileOutlined
}

/**
 * 根据文件名解析图标组件。
 */
const getFileIconComponent = (fileName: string): Component => {
  const iconType = getFileIconType(fileName)
  return fileIconComponentMap[iconType] || FileOutlined
}

/**
 * 处理节点选择。
 */
const onSelect: TreeProps['onSelect'] = (keys) => {
  const selectedKeysArr = keys as string[]
  const nodes = selectedKeysArr
    .map((key) => getOriginalNode(key))
    .filter((node): node is T => Boolean(node))
  emit('select', selectedKeysArr, nodes)
}

/**
 * 处理节点拖拽，先本地更新避免回弹。
 */
const findParentKeyInTree = (nodes: T[], targetKey: string, isInsertInto: boolean): string | null => {
  if (isInsertInto) return targetKey

  const findParent = (items: T[], key: string, parentKey: string | null): string | null | undefined => {
    for (const item of items) {
      if (item.key === key) return parentKey
      if (item.children?.length) {
        const found = findParent(item.children as T[], key, item.key)
        if (found !== undefined) return found
      }
    }
    return undefined
  }

  const result = findParent(nodes, targetKey, null)
  return result === undefined ? null : result
}

const getSiblingsAtLevel = (nodes: T[], parentKey: string | null): T[] => {
  if (!parentKey) return nodes

  const findChildren = (items: T[], key: string): T[] | null => {
    for (const item of items) {
      if (item.key === key) return (item.children as T[]) || []
      if (item.children?.length) {
        const found = findChildren(item.children as T[], key)
        if (found) return found
      }
    }
    return null
  }

  return findChildren(nodes, parentKey) || []
}

const removeNodeFromTree = (nodes: T[], key: string): T | undefined => {
  for (let index = 0; index < nodes.length; index += 1) {
    if (nodes[index].key === key) {
      const removed = nodes[index]
      nodes.splice(index, 1)
      return removed
    }
    const childNodes = nodes[index].children
    if (childNodes) {
      const found = removeNodeFromTree(childNodes as T[], key)
      if (found) return found
    }
  }
  return undefined
}

const hasDescendant = (root: T | undefined, targetKey: string): boolean => {
  if (!root?.children?.length) return false
  for (const child of root.children) {
    if (child.key === targetKey || hasDescendant(child as T, targetKey)) return true
  }
  return false
}

const onDrop: TreeProps['onDrop'] = (info) => {
  const dropInfo = info as unknown as AntTreeDropInfo
  const { dragNode, node: dropNode } = dropInfo
  if (!dragNode || !dropNode) return

  const dragKeys: string[] = dropInfo.dragNodesKeys
    ? dropInfo.dragNodesKeys.map(String)
    : [String(dragNode.key)]

  if (dragKeys.includes(String(dropNode.key))) {
    emit('drop-invalid', 'same-node')
    return
  }

  for (const key of dragKeys) {
    const sourceNode = getOriginalNode(key)
    if (hasDescendant(sourceNode, String(dropNode.key))) {
      emit('drop-invalid', 'drop-to-descendant')
      return
    }
  }

  const data = cloneTree(internalTreeData.value)
  const dragObjs: T[] = []

  for (const key of dragKeys) {
    const obj = removeNodeFromTree(data, key)
    if (obj) dragObjs.push(obj)
  }

  if (!dragObjs.length) return

  const dropToGap = Boolean(dropInfo.dropToGap)
  const pos = String(dropNode.pos || '')
  const posParts = pos.split('-')
  const nodeIndex = Number(posParts[posParts.length - 1] || 0)
  const relativeDropPosition = (dropInfo.dropPosition || 0) - nodeIndex
  const isDropNodeFolder = dropNode.dataRef?.isFolder === true
  const shouldInsertInto = !dropToGap && isDropNodeFolder

  if (!dropToGap && !isDropNodeFolder) {
    emit('drop-invalid', 'drop-into-file')
    return
  }

  if (shouldInsertInto) {
    const insertInto = (nodes: T[]): boolean => {
      for (let index = 0; index < nodes.length; index += 1) {
        if (nodes[index].key === dropNode.key) {
          if (!nodes[index].children) {
            nodes[index].children = []
          }
          const childNodes = nodes[index].children || []
          for (const obj of dragObjs) {
            childNodes.push(obj)
          }
          nodes[index].children = childNodes
          return true
        }
        const childNodes = nodes[index].children
        if (childNodes && insertInto(childNodes as T[])) {
          return true
        }
      }
      return false
    }
    insertInto(data)
  } else {
    let offset = 0
    const insertAtGap = (nodes: T[]): boolean => {
      for (let index = 0; index < nodes.length; index += 1) {
        if (nodes[index].key === dropNode.key) {
          const insertIndex = relativeDropPosition < 0 ? index : index + 1
          for (let i = 0; i < dragObjs.length; i++) {
            nodes.splice(insertIndex + offset + i, 0, dragObjs[i])
          }
          return true
        }
        const childNodes = nodes[index].children
        if (childNodes && insertAtGap(childNodes as T[])) {
          return true
        }
      }
      return false
    }
    insertAtGap(data)
  }

  internalTreeData.value = data

  const targetParentKey = findParentKeyInTree(data, String(dropNode.key), shouldInsertInto)
  const siblings = getSiblingsAtLevel(data, targetParentKey)

  const dropEvent: DropEvent = {
    dragKey: String(dragNode.key),
    dragKeys,
    dragNode: dragObjs[0],
    dragNodes: dragObjs,
    dropKey: String(dropNode.key),
    dropNode: getOriginalNode(String(dropNode.key)) || (dropNode.dataRef as T),
    dropToGap,
    targetParentKey,
    siblings,
    resultTree: data,
  }

  emit('drop', dropEvent)
}

const onNodeDragStart: TreeProps['onDragstart'] = (info) => {
  const dragInfo = info as unknown as AntTreeDragInfo
  const keys = dragInfo.selectedKeys?.map(String) || [String(dragInfo.node?.key ?? '')]
  draggingNodeKeys.value = keys
}

const onNodeDragEnd: TreeProps['onDragend'] = () => {
  draggingNodeKeys.value = []
}

/** 容器级 dragend 清空拖拽状态，避免移出 a-tree 区域时过早丢失 draggingNodeKey */
const onContainerDragEnd = () => {
  draggingNodeKeys.value = []
}

const onRootDragEnter = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes('Files')) return
  event.preventDefault()
}

const onRootDragOver = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes('Files')) return
  event.preventDefault()
}

const onRootDragLeave = (_event: DragEvent) => {
}

const onRootDrop = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes('Files')) return
  if (!draggingNodeKeys.value.length) return
  emit('drop-root', [...draggingNodeKeys.value])
  draggingNodeKeys.value = []
}

/**
 * 触发搜索事件。
 */
const onSearch = () => {
  emit('search', searchText.value)
}

/**
 * 处理文件拖入覆盖层。
 */
const onFileDragOver = (event: DragEvent) => {
  if (!event.dataTransfer?.types.includes('Files')) return
  isDraggingFile.value = true
  event.preventDefault()
  const target = event.target as HTMLElement | null
  const treeNodeElement = target?.closest('.ant-tree-treenode') as HTMLElement | null
  const nodeKey = treeNodeElement?.getAttribute('data-node-key')
  if (!nodeKey) {
    dragOverKey.value = null
    return
  }
  const node = getOriginalNode(nodeKey)
  dragOverKey.value = node?.isFolder ? nodeKey : null
}

/**
 * 处理文件拖离覆盖层。
 */
const onFileDragLeave = (event: DragEvent) => {
  const rect = (event.currentTarget as HTMLElement).getBoundingClientRect()
  const { clientX, clientY } = event
  if (clientX < rect.left || clientX > rect.right || clientY < rect.top || clientY > rect.bottom) {
    isDraggingFile.value = false
    dragOverKey.value = null
  }
}

/**
 * 处理文件拖拽上传。
 */
const onFileDrop = (event: DragEvent) => {
  isDraggingFile.value = false
  const files = event.dataTransfer?.files
  if (files && files.length > 0) {
    event.preventDefault()
    const fileArray = Array.from(files)
    const targetFolder = dragOverKey.value ? getOriginalNode(dragOverKey.value) : null
    emit('file-drop', fileArray, targetFolder as T | null)
  }
  dragOverKey.value = null
}

/**
 * 获取允许上传的文件类型说明。
 */
const getAllowedFileTypesDesc = (): string => {
  if (!props.allowedFileTypes || props.allowedFileTypes.length === 0) {
    return '所有文件'
  }
  return props.allowedFileTypes.join(', ')
}

/**
 * 展开所有节点。
 */
const expandAll = () => {
  const getAllKeys = (nodes: T[]): string[] => {
    const keys: string[] = []
    for (const node of nodes) {
      if (node.children && node.children.length > 0) {
        keys.push(node.key)
        keys.push(...getAllKeys(node.children as T[]))
      }
    }
    return keys
  }
  expandedKeys.value = getAllKeys(props.treeData)
}

/**
 * 收起所有节点。
 */
const collapseAll = () => {
  expandedKeys.value = []
}

/**
 * 获取当前选中的节点。
 */
const getSelectedNodes = (): T[] => {
  const findNodes = (nodes: T[], keys: string[]): T[] => {
    const result: T[] = []
    for (const node of nodes) {
      if (keys.includes(node.key)) {
        result.push(node)
      }
      if (node.children) {
        result.push(...findNodes(node.children as T[], keys))
      }
    }
    return result
  }
  return findNodes(props.treeData, selectedKeys.value)
}

/**
 * 校验文件类型是否允许上传。
 */
const validateFileType = (file: File): boolean => {
  if (!props.allowedFileTypes || props.allowedFileTypes.length === 0) {
    return true
  }
  const fileName = file.name.toLowerCase()
  return props.allowedFileTypes.some((ext) => fileName.endsWith(ext.toLowerCase()))
}

defineExpose({
  expandAll,
  collapseAll,
  getSelectedNodes,
  validateFileType,
  getAllowedFileTypesDesc,
  searchText,
  expandedKeys,
  selectedKeys
})
</script>

<style lang="less" scoped>
.smart-tree {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;

  &.dark-mode {
    :deep(.ant-tree) {
      color: rgba(255, 255, 255, 0.85);

      .ant-tree-node-content-wrapper {
        &:hover {
          background: rgba(255, 255, 255, 0.06);
        }

        &.ant-tree-node-selected {
          background: rgba(23, 125, 220, 0.4);
          position: relative;
          overflow: visible;

          &::before {
            content: '';
            position: absolute;
            left: -5px;
            top: 50%;
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--primary-color, #177ddc);
            transform: translateY(-50%);
            z-index: 1;
          }

          &:has(.tree-node-default.is-folder)::before {
            display: none;
          }
        }
      }
    }

    .tree-search {
      border-bottom-color: rgba(255, 255, 255, 0.08);

      :deep(.ant-input) {
        .ant-input-affix-wrapper {
          .search-icon {
            color: rgba(255, 255, 255, 0.45);
          }
        }
      }

      .search-add-btn {
        color: rgba(255, 255, 255, 0.65);

        &:hover {
          color: var(--primary-color, #1890ff);
        }
      }
    }

    .tree-node-default {
      .node-icon {
        color: rgba(255, 255, 255, 0.55);

        .anticon-folder {
          color: var(--tree-folder-color, #f0b90b);
        }

        .anticon-file {
          color: rgba(255, 255, 255, 0.45);
        }
      }

      .node-actions {
        background: linear-gradient(to right, transparent, var(--panel-bg, #ffffff) 10px);

        :deep(.action-btn) {
          display: inline-flex;
          align-items: center;
          justify-content: center;
          font-size: 12px;
          line-height: 1;
          color: rgba(255, 255, 255, 0.55);
          cursor: pointer;
          padding: 2px;
          border: none;
          background: transparent;
          border-radius: 3px;
          transition: all 0.2s;
          pointer-events: auto;

          &:hover {
            color: var(--primary-color, #177ddc);
            background: rgba(24, 144, 255, 0.15);
          }

          &.delete:hover {
            color: var(--tree-danger-color, #e05353);
            background: rgba(255, 77, 79, 0.15);
          }
        }
      }
    }

    .tree-content {
      .root-drop-zone {
        border-color: rgba(24, 144, 255, 0.4);
        color: var(--primary-color, #1890ff);
        background: var(--tree-drop-zone-bg, rgba(24, 144, 255, 0.06));
      }
    }
  }

  .tree-search {
    padding: 6px 6px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.06);
    flex-shrink: 0;
    display: flex;
    align-items: center;
    gap: 2px;

    :deep(.ant-input) {
      flex: 1;
      border-radius: 4px;

      .ant-input-affix-wrapper {
        padding: 4px 11px;

        .ant-input {
          font-size: 13px;
        }

        .search-icon {
          color: rgba(0, 0, 0, 0.25);
          margin-right: 4px;
        }
      }
    }

    .search-add-btn {
      flex-shrink: 0;
      height: 32px;
      width: 32px;
      padding: 0;
      display: flex;
      align-items: center;
      justify-content: center;
      background: transparent;
      border: none;
      box-shadow: none;
      color: rgba(0, 0, 0, 0.45);
      cursor: pointer;
      transition: color 0.3s;

      &:hover {
        color: var(--primary-color, #1890ff);
      }

      .anticon {
        font-size: 16px;
      }
    }
  }

  .tree-content {
    flex: 1;
    overflow: auto;
    padding: 4px 0;

    .root-drop-zone {
      margin: 8px 8px 4px;
      border: 1px dashed var(--tree-drop-border, rgba(24, 144, 255, 0.5));
      border-radius: 6px;
      color: var(--primary-color, #1890ff);
      background: var(--tree-drop-zone-bg, rgba(24, 144, 255, 0.06));
      text-align: center;
      line-height: 32px;
      font-size: 12px;
      user-select: none;
    }

    :deep(.ant-tree) {
      background: transparent;

      .ant-tree-treenode {
        padding: 0 !important;
        margin: 0;

        .ant-tree-indent {
          .ant-tree-indent-unit {
            width: 10px;
          }
        }

        &[data-level="0"] {
          > .ant-tree-switcher {
            margin-left: 0;
          }

          > .ant-tree-node-content-wrapper {
            padding-left: 4px !important;
          }
        }
      }

      .ant-tree-title {
        font-size: 13px;
        display: block;
        width: 100%;
        overflow: hidden;
        min-width: 0;
      }

      .ant-tree-switcher {
        width: 12px;
        height: 22px;
        line-height: 22px;
        margin-left: 2px;
        display: flex;
        align-items: center;
        justify-content: center;

        .ant-tree-switcher-icon {
          display: flex;
          align-items: center;
          justify-content: center;
        }
      }

      .ant-tree-node-content-wrapper {
        height: 100% !important;
        line-height: normal !important;
        display: flex;
        align-items: center;
        border-radius: 4px;
        transition: background 0.2s;
        width: 100%;
        min-width: 0;
        overflow: hidden;
        padding: 0 2px !important;

        &:hover {
          background: rgba(0, 0, 0, 0.04);
        }

        &.ant-tree-node-selected {
          background: rgba(24, 144, 255, 0.28);
          position: relative;
          overflow: visible;

          &::before {
            content: '';
            position: absolute;
            left: -5px;
            top: 50%;
            width: 5px;
            height: 5px;
            border-radius: 50%;
            background: var(--primary-color, #1890ff);
            transform: translateY(-50%);
            z-index: 1;
          }

          &:has(.tree-node-default.is-folder)::before {
            display: none;
          }
        }
      }

      .ant-tree-treenode {
        padding: 1px 0;
        margin: 0;
        height: 22px !important;
        min-height: 22px !important;
        display: flex;
        align-items: center;
      }
    }
  }

  .tree-node-default {
    display: flex;
    align-items: center;
    justify-content: flex-start;
    width: 100%;
    height: 100%;
    gap: 3px;
    position: relative;
    min-width: 0;
    overflow: hidden !important;
    box-sizing: border-box;

    &.is-folder {
      font-weight: 500;
    }

    &.level-0 {
      margin-left: 0;
    }

    .node-icon {
      flex-shrink: 0 !important;
      display: flex;
      align-items: center;
      justify-content: center;
      width: 16px;
      height: 16px;
      font-size: 14px;
      color: var(--text-secondary, rgba(0, 0, 0, 0.65));
      line-height: 1;
      overflow: visible;
      margin-left: 0;

      .anticon {
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .anticon-folder {
        color: var(--tree-folder-color, #f0b90b);
      }

      .anticon-file {
        color: var(--text-secondary, rgba(0, 0, 0, 0.65));
      }
    }

    .node-title {
      flex: 1 1 auto !important;
      overflow: hidden !important;
      text-overflow: ellipsis !important;
      white-space: nowrap !important;
      min-width: 0 !important;
      max-width: 100% !important;
      height: 100%;
      display: flex;
      align-items: center;

      span {
        overflow: hidden !important;
        text-overflow: ellipsis !important;
        white-space: nowrap !important;
        display: inline-block;
        max-width: 100%;
        vertical-align: middle;
      }

      mark {
        border-radius: 2px;
      }
    }

    .node-status {
      flex-shrink: 0 !important;
      margin-right: 4px;
      display: flex;
      align-items: center;
      line-height: 1;
      height: 100%;

      :deep(.ant-tag) {
        font-size: 10px;
        padding: 0 4px;
        line-height: 16px;
        margin: 0;
        display: inline-flex;
        align-items: center;
      }
    }

    .node-actions {
      display: flex !important;
      align-items: center;
      justify-content: center;
      gap: 2px;
      flex-shrink: 0 !important;
      opacity: 0;
      transition: opacity 0.2s;
      position: absolute;
      right: 0;
      top: 0;
      bottom: 0;
      background: linear-gradient(to right, transparent, var(--panel-bg, #ffffff) 10px);
      padding-left: 16px;
      z-index: 10;
      pointer-events: none;

      :deep(.action-btn) {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        font-size: 12px;
        line-height: 1;
        color: var(--text-secondary, rgba(0, 0, 0, 0.65));
        cursor: pointer;
        padding: 2px;
        border: none;
        background: transparent;
        border-radius: 3px;
        transition: all 0.2s;
        pointer-events: auto;

        &:hover {
          color: var(--primary-color, #1890ff);
          background: rgba(24, 144, 255, 0.1);
        }

        &.delete:hover {
          color: var(--tree-danger-hover, #cf1322);
          background: rgba(255, 77, 79, 0.1);
        }
      }
    }

    &:hover .node-actions {
      opacity: 1;
    }
  }

  .tree-empty {
    padding: 32px 0;
    text-align: center;

    .add-root-btn {
      margin-top: 12px;
    }
  }

  .tree-loading {
    padding: 16px 0;
    text-align: center;
  }

  .file-drop-hint {
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    bottom: 0;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: rgba(24, 144, 255, 0.9);
    color: #fff;
    font-size: 16px;
    z-index: 100;
    gap: 8px;

    .anticon {
      font-size: 32px;
    }
  }
}
</style>
