<template>
  <div
    class="smart-tree"
    :class="{ 'dark-mode': isDark }"
    @dragover="onFileDragOver"
    @dragleave="onFileDragLeave"
    @drop="onFileDrop"
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
      <div
        v-if="showAddRootFolder"
        class="search-add-btn"
        :title="addRootFolderTitle"
        @click="$emit('add-folder', null)"
      >
        <FolderAddOutlined />
      </div>
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
                      <a-tooltip title="重命名">
                        <EditOutlined class="action-icon" @click="onRename(key)" />
                      </a-tooltip>
                      <a-tooltip title="添加子文件夹">
                        <FolderAddOutlined class="action-icon" @click="onAddFolder(key)" />
                      </a-tooltip>
                      <a-tooltip v-if="allowAddFile" title="添加文件">
                        <FileAddOutlined class="action-icon" @click="onAddFile(key)" />
                      </a-tooltip>
                      <a-tooltip title="删除">
                        <DeleteOutlined class="action-icon delete" @click="onDelete(key)" />
                      </a-tooltip>
                    </template>
                    <template v-else>
                      <a-tooltip title="重命名">
                        <EditOutlined class="action-icon" @click="onRename(key)" />
                      </a-tooltip>
                      <a-tooltip title="查看">
                        <EyeOutlined class="action-icon" @click="onView(key)" />
                      </a-tooltip>
                      <a-tooltip title="删除">
                        <DeleteOutlined class="action-icon delete" @click="onDelete(key)" />
                      </a-tooltip>
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
        v-if="draggable && draggingNodeKey"
        class="root-drop-zone"
        @dragover.prevent="onRootDragOver"
        @drop.prevent="onRootDrop"
      >
        拖到此处移动到根目录
      </div>

      <div v-if="!filteredTreeData.length && !loading" class="tree-empty">
        <slot name="empty">
          <a-empty :description="searchText ? '无匹配结果' : emptyText" />
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
        <span>释放上传至 {{ dragOverKey && getOriginalNode(dragOverKey) ? getOriginalNode(dragOverKey)?.title : '根目录' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 通用智能树组件。
 * 支持搜索、拖拽、自定义渲染，适用于知识树、经验树等多种场景。
 */
import { computed, ref, watch, type Component } from 'vue'
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
  FolderAddOutlined,
  FolderOutlined,
  SearchOutlined
} from '@ant-design/icons-vue'
import { useTheme } from '../../composables/useTheme'
import type { SmartTreeNode } from '../../types/tree'

export type { SmartTreeNode }

/**
 * 高亮文本中的搜索关键字。
 */
const highlightText = (text: string, keyword: string): string => {
  if (!keyword) return text
  const escapedKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
  const regex = new RegExp(`(${escapedKeyword})`, 'gi')
  return text.replace(regex, '<mark>$1</mark>')
}

/**
 * 根据文件名推断图标类型。
 */
const getFileIconType = (fileName: string): string => {
  const lowerFileName = fileName.toLowerCase()
  if (lowerFileName.endsWith('.pdf')) return 'pdf'
  if (/\.(doc|docx)$/.test(lowerFileName)) return 'word'
  if (/\.(xls|xlsx|csv)$/.test(lowerFileName)) return 'excel'
  if (/\.(ppt|pptx)$/.test(lowerFileName)) return 'ppt'
  if (/\.(jpg|jpeg|png|gif|webp|svg)$/.test(lowerFileName)) return 'image'
  if (/\.(zip|rar|7z|tar|gz)$/.test(lowerFileName)) return 'zip'
  if (lowerFileName.endsWith('.md')) return 'markdown'
  if (/\.(txt|json|yaml|yml|xml)$/.test(lowerFileName)) return 'text'
  return 'file'
}

/**
 * 获取文件图标颜色。
 */
const getFileIconColor = (fileName: string): string => {
  const iconType = getFileIconType(fileName)
  const colorMap: Record<string, string> = {
    pdf: '#ff4d4f',
    word: '#1890ff',
    excel: '#52c41a',
    ppt: '#fa8c16',
    image: '#722ed1',
    zip: '#8c8c8c',
    markdown: '#13c2c2',
    text: '#8c8c8c',
    file: '#8c8c8c'
  }
  return colorMap[iconType] || colorMap.file
}

/**
 * 获取状态颜色。
 */
const getStatusColor = (status: string): string => {
  const colorMap: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    failed: 'error'
  }
  return colorMap[status] || 'default'
}

/**
 * 获取状态文案。
 */
const getStatusText = (status: string): string => {
  const textMap: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败'
  }
  return textMap[status] || status || '未知'
}

/**
 * 根据关键字过滤树节点。
 */
function filterTree<T extends { title: string; children?: T[] }>(nodes: T[], keyword: string): T[] {
  return nodes.reduce<T[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const filteredChildren = node.children ? filterTree(node.children, keyword) : []
    if (title.includes(keyword) || filteredChildren.length > 0) {
      result.push({
        ...node,
        children: filteredChildren
      })
    }
    return result
  }, [])
}

/**
 * 收集搜索命中路径上的父节点 key。
 */
function getExpandedKeysForSearch<T extends { key: string; title: string; children?: T[] }>(
  nodes: T[],
  keyword: string,
  parentKeys: string[] = []
): string[] {
  return nodes.reduce<string[]>((result, node) => {
    const title = String(node.title || '').toLowerCase()
    const currentParentKeys = [...parentKeys, node.key]
    const childKeys = node.children
      ? getExpandedKeysForSearch(node.children, keyword, currentParentKeys)
      : []
    if (title.includes(keyword)) {
      result.push(...parentKeys)
    }
    result.push(...childKeys)
    return result
  }, [])
}

interface Props {
  treeData: SmartTreeNode[]
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

const props = withDefaults(defineProps<Props>(), {
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
  allowAddFile: true,
  allowedFileTypes: () => ['.pdf'],
  loading: false,
  emptyText: '暂无数据',
  defaultExpandedKeys: () => [],
  defaultSelectedKeys: () => []
})

const emit = defineEmits<{
  select: [keys: string[], nodes: SmartTreeNode[]]
  rename: [node: SmartTreeNode]
  'add-folder': [node: SmartTreeNode | null]
  'add-file': [node: SmartTreeNode]
  delete: [node: SmartTreeNode]
  view: [node: SmartTreeNode]
  drop: [info: any]
  search: [text: string]
  'file-drop': [files: File[], targetFolder: SmartTreeNode | null]
  'drop-invalid': [reason: string]
  'drop-root': [dragNodeKey: string]
}>()

const { isDark } = useTheme()
const searchText = ref('')
const expandedKeys = ref<string[]>(props.defaultExpandedKeys)
const selectedKeys = ref<string[]>(props.defaultSelectedKeys)
const internalTreeData = ref<SmartTreeNode[]>([])
const isDraggingFile = ref(false)
const dragOverKey = ref<string | null>(null)
const draggingNodeKey = ref<string | null>(null)

const sourceTreeData = computed(() => {
  if (internalTreeData.value.length === 0 && props.treeData.length > 0) {
    return props.treeData
  }
  return internalTreeData.value
})

const originalNodeMap = computed(() => {
  const map = new Map<string, SmartTreeNode>()
  const walk = (nodes: SmartTreeNode[]) => {
    for (const node of nodes) {
      map.set(node.key, node)
      if (node.children?.length) {
        walk(node.children)
      }
    }
  }
  walk(props.treeData)
  return map
})

watch(() => props.treeData, (value) => {
  internalTreeData.value = JSON.parse(JSON.stringify(value))
}, { immediate: true, deep: true })

watch(() => props.defaultExpandedKeys, (value) => {
  expandedKeys.value = value
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
const getOriginalNode = (key: string): SmartTreeNode | undefined => {
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

const onNodeDblClick = (node: SmartTreeNode) => {
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
const onSelect: TreeProps['onSelect'] = (keys, info) => {
  emit('select', keys as string[], info.selectedNodes as SmartTreeNode[])
}

/**
 * 处理节点拖拽，先本地更新避免回弹。
 */
const onDrop: TreeProps['onDrop'] = (info) => {
  const { dragNode, node: dropNode } = info
  if (!dragNode || !dropNode) return
  if (dragNode.key === dropNode.key) {
    emit('drop-invalid', 'same-node')
    return
  }

  const hasNodeInSubTree = (root: SmartTreeNode | undefined, targetKey: string): boolean => {
    if (!root?.children?.length) return false
    for (const child of root.children) {
      if (child.key === targetKey || hasNodeInSubTree(child, targetKey)) return true
    }
    return false
  }

  const sourceNode = getOriginalNode(String(dragNode.key))
  if (hasNodeInSubTree(sourceNode, String(dropNode.key))) {
    emit('drop-invalid', 'drop-to-descendant')
    return
  }

  const data = JSON.parse(JSON.stringify(internalTreeData.value))
  let dragObj: SmartTreeNode | undefined

  const removeNode = (nodes: SmartTreeNode[]): boolean => {
    for (let index = 0; index < nodes.length; index += 1) {
      if (nodes[index].key === dragNode.key) {
        dragObj = nodes[index]
        nodes.splice(index, 1)
        return true
      }
      const childNodes = nodes[index].children
      if (childNodes && removeNode(childNodes)) {
        return true
      }
    }
    return false
  }
  removeNode(data)

  if (!dragObj) return

  const dropToGap = (info as any).dropToGap
  const pos = String((dropNode as any).pos || '')
  const posParts = pos.split('-')
  const nodeIndex = Number(posParts[posParts.length - 1] || 0)
  const relativeDropPosition = ((info as any).dropPosition as number) - nodeIndex
  const isDropNodeFolder = (dropNode as any).dataRef?.isFolder === true
  const shouldInsertInto = !dropToGap && isDropNodeFolder

  if (!dropToGap && !isDropNodeFolder) {
    emit('drop-invalid', 'drop-into-file')
    return
  }

  if (shouldInsertInto) {
    const insertInto = (nodes: SmartTreeNode[]): boolean => {
      for (let index = 0; index < nodes.length; index += 1) {
        if (nodes[index].key === dropNode.key) {
          if (!nodes[index].children) {
            nodes[index].children = []
          }
          const childNodes = nodes[index].children || []
          childNodes.push(dragObj!)
          nodes[index].children = childNodes
          return true
        }
        const childNodes = nodes[index].children
        if (childNodes && insertInto(childNodes)) {
          return true
        }
      }
      return false
    }
    insertInto(data)
  } else {
    const insertAt = (nodes: SmartTreeNode[]): boolean => {
      for (let index = 0; index < nodes.length; index += 1) {
        if (nodes[index].key === dropNode.key) {
          const insertIndex = relativeDropPosition < 0 ? index : index + 1
          nodes.splice(insertIndex, 0, dragObj!)
          return true
        }
        const childNodes = nodes[index].children
        if (childNodes && insertAt(childNodes)) {
          return true
        }
      }
      return false
    }
    insertAt(data)
  }

  internalTreeData.value = data
  emit('drop', info)
}

const onNodeDragStart: TreeProps['onDragstart'] = (info) => {
  draggingNodeKey.value = String(info.node?.key || '')
}

const onNodeDragEnd: TreeProps['onDragend'] = () => {
  draggingNodeKey.value = null
}

const onRootDragOver = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes('Files')) return
  event.preventDefault()
}

const onRootDrop = (event: DragEvent) => {
  if (event.dataTransfer?.types.includes('Files')) return
  if (!draggingNodeKey.value) return
  emit('drop-root', draggingNodeKey.value)
  draggingNodeKey.value = null
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
    emit('file-drop', fileArray, targetFolder as SmartTreeNode | null)
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
  const getAllKeys = (nodes: SmartTreeNode[]): string[] => {
    const keys: string[] = []
    for (const node of nodes) {
      if (node.children && node.children.length > 0) {
        keys.push(node.key)
        keys.push(...getAllKeys(node.children))
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
const getSelectedNodes = (): SmartTreeNode[] => {
  const findNodes = (nodes: SmartTreeNode[], keys: string[]): SmartTreeNode[] => {
    const result: SmartTreeNode[] = []
    for (const node of nodes) {
      if (keys.includes(node.key)) {
        result.push(node)
      }
      if (node.children) {
        result.push(...findNodes(node.children, keys))
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
    }

    .tree-search {
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
          color: #1890ff;
        }
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
        color: #1890ff;
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
      border: 1px dashed #91caff;
      border-radius: 6px;
      color: #1677ff;
      background: #f0f8ff;
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
          background: rgba(24, 144, 255, 0.1);
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
      color: #8c8c8c;
      line-height: 1;
      overflow: visible;
      margin-left: 0;

      .anticon {
        display: flex;
        align-items: center;
        justify-content: center;
      }

      .anticon-folder {
        color: #faad14;
      }

      .anticon-file {
        color: #8c8c8c;
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
      background: linear-gradient(to right, transparent, var(--bg-color, #fff) 10px);
      padding-left: 16px;
      z-index: 10;
      pointer-events: none;

      .action-icon {
        font-size: 12px;
        color: #8c8c8c;
        cursor: pointer;
        padding: 2px;
        border-radius: 3px;
        transition: all 0.2s;
        pointer-events: auto;

        &:hover {
          color: #1890ff;
          background: rgba(24, 144, 255, 0.1);
        }

        &.delete:hover {
          color: #ff4d4f;
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
