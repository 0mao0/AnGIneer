<template>
  <!-- 通用智能树组件 - 支持搜索、自定义操作按钮和灵活的数据结构 -->
  <div 
    class="smart-tree" 
    :class="{ 'dark-mode': isDark }"
    @dragover="onFileDragOver"
    @dragleave="onFileDragLeave"
    @drop="onFileDrop"
  >
    <!-- 搜索栏 -->
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

    <!-- 树内容区 -->
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
        <template #title="{ title, key }">
          <!-- 从原始数据中查找完整节点信息 -->
          <template v-if="getOriginalNode(key)">
            <slot name="node" :node="getOriginalNode(key)">
              <!-- 默认节点渲染 -->
              <div
                class="tree-node-default"
                :class="{
                  'is-folder': getOriginalNode(key)?.isFolder,
                  'is-leaf': !getOriginalNode(key)?.isFolder,
                  [`level-${getOriginalNode(key)?.level || 0}`]: true
                }"
              >
                <!-- 节点图标 -->
                <span v-if="showIcon" class="node-icon">
                  <slot name="icon" :node="getOriginalNode(key)">
                    <FolderOutlined v-if="getOriginalNode(key)?.isFolder" />
                    <FilePdfOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'pdf'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileWordOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'word'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileExcelOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'excel'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FilePptOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'ppt'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileImageOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'image'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileZipOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'zip'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileTextOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'text'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileMarkdownOutlined v-else-if="getFileIconType(getOriginalNode(key)?.title || '') === 'markdown'" :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                    <FileOutlined v-else :style="{ color: getFileIconColor(getOriginalNode(key)?.title || '') }" />
                  </slot>
                </span>

                <!-- 节点标题 -->
                <span class="node-title" :title="title">
                  <slot name="title" :node="getOriginalNode(key)">
                    <span v-if="searchText && highlightSearch" v-html="highlightText(title)" />
                    <span v-else>{{ title }}</span>
                  </slot>
                </span>

                <!-- 节点状态标签 - 仅文件显示，文件夹不显示 -->
                <span v-if="!getOriginalNode(key)?.isFolder && getOriginalNode(key)?.status && showStatus" class="node-status">
                  <slot name="status" :node="getOriginalNode(key)">
                    <a-tag :color="getStatusColor(getOriginalNode(key)?.status || '')" size="small">
                      {{ getStatusText(getOriginalNode(key)?.status || '') }}
                    </a-tag>
                  </slot>
                </span>

                <!-- 节点操作按钮 -->
                <span class="node-actions" @click.stop>
                  <slot name="actions" :node="getOriginalNode(key)">
                    <!-- 文件夹操作 -->
                    <template v-if="getOriginalNode(key)?.isFolder">
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
                    <!-- 文件操作 -->
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
          <!-- 找不到节点时的回退显示 -->
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

      <!-- 空状态 -->
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

      <!-- 加载状态 -->
      <div v-if="loading" class="tree-loading">
        <a-spin size="small" />
      </div>

      <!-- 文件拖拽提示 -->
      <div v-if="isDraggingFile" class="file-drop-hint">
        <CloudUploadOutlined />
        <span>释放上传至 {{ dragOverKey && getOriginalNode(dragOverKey) ? getOriginalNode(dragOverKey)?.title : '根目录' }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 通用智能树组件
 * 支持搜索、拖拽、自定义渲染，适用于知识树、经验树等多种场景
 */
import { ref, computed, watch } from 'vue'
import {
  FolderOutlined,
  FileOutlined,
  FilePdfOutlined,
  FileWordOutlined,
  FileExcelOutlined,
  FilePptOutlined,
  FileImageOutlined,
  FileZipOutlined,
  FileTextOutlined,
  FileMarkdownOutlined,
  CloudUploadOutlined,
  EditOutlined,
  FolderAddOutlined,
  FileAddOutlined,
  DeleteOutlined,
  EyeOutlined,
  SearchOutlined
} from '@ant-design/icons-vue'
import { useTheme } from '@angineer/ui-kit'
import type { TreeProps } from 'ant-design-vue'
import type { SmartTreeNode } from '../../types/tree'

export type { SmartTreeNode }

/** 组件 Props */
interface Props {
  /** 树数据 */
  treeData: SmartTreeNode[]
  /** 是否显示搜索框 */
  showSearch?: boolean
  /** 搜索框占位符 */
  searchPlaceholder?: string
  /** 是否高亮搜索结果 */
  highlightSearch?: boolean
  /** 是否显示新增一级目录按钮 */
  showAddRootFolder?: boolean
  /** 新增一级目录按钮文本 */
  addRootFolderText?: string
  /** 新增一级目录按钮标题 */
  addRootFolderTitle?: string
  /** 是否显示图标 */
  showIcon?: boolean
  /** 是否显示状态标签 */
  showStatus?: boolean
  /** 是否显示连接线 */
  showLine?: boolean
  /** 是否允许拖拽 */
  draggable?: boolean
  /** 是否允许添加文件 */
  allowAddFile?: boolean
  /** 允许上传的文件类型，如 ['.pdf', '.doc']，默认 ['.pdf'] */
  allowedFileTypes?: string[]
  /** 加载状态 */
  loading?: boolean
  /** 空状态文本 */
  emptyText?: string
  /** 默认展开keys */
  defaultExpandedKeys?: string[]
  /** 默认选中keys */
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
  /** 选择节点 */
  select: [keys: string[], nodes: SmartTreeNode[]]
  /** 重命名节点 */
  rename: [node: SmartTreeNode]
  /** 添加子文件夹 */
  'add-folder': [node: SmartTreeNode | null]
  /** 添加文件 */
  'add-file': [node: SmartTreeNode]
  /** 删除节点 */
  delete: [node: SmartTreeNode]
  /** 查看节点 */
  view: [node: SmartTreeNode]
  /** 节点拖拽 */
  drop: [info: any]
  /** 搜索 */
  search: [text: string]
  /** 文件拖拽上传 */
  'file-drop': [files: File[], targetFolder: SmartTreeNode | null]
  /** 无效拖拽 */
  'drop-invalid': [reason: string]
  /** 拖拽到根目录 */
  'drop-root': [dragNodeKey: string]
}>()

// 主题
const { isDark } = useTheme()

// 搜索文本
const searchText = ref('')

// 展开和选中的keys
const expandedKeys = ref<string[]>(props.defaultExpandedKeys)
const selectedKeys = ref<string[]>(props.defaultSelectedKeys)

// 内部树数据（用于拖拽时本地更新）
const internalTreeData = ref<SmartTreeNode[]>([])

// 文件拖拽上传相关状态
const isDraggingFile = ref(false)
const dragOverKey = ref<string | null>(null)
const draggingNodeKey = ref<string | null>(null)

const sourceTreeData = computed(() => {
  if (internalTreeData.value.length === 0 && props.treeData.length > 0) {
    return props.treeData
  }
  return internalTreeData.value
})

// 监听props变化，同步到内部数据
watch(() => props.treeData, (val) => {
  internalTreeData.value = JSON.parse(JSON.stringify(val))
}, { immediate: true, deep: true })

// 监听props变化
watch(() => props.defaultExpandedKeys, (val) => {
  expandedKeys.value = val
}, { immediate: true })

watch(() => props.defaultSelectedKeys, (val) => {
  selectedKeys.value = val
}, { immediate: true })

/**
 * 过滤树数据 - 根据搜索文本递归过滤
 */
const filteredTreeData = computed(() => {
  if (!searchText.value) return sourceTreeData.value
  const result = filterTree(sourceTreeData.value, searchText.value.toLowerCase())
  return result
})

/**
 * 收集所有需要展开的父节点 keys（搜索时自动展开匹配路径）
 */
const getExpandedKeysForSearch = (nodes: SmartTreeNode[], keyword: string, parentKeys: string[] = []): string[] => {
  const expandedKeys: string[] = []
  
  for (const node of nodes) {
    const matchTitle = node.title.toLowerCase().includes(keyword)
    const childKeys = node.children ? getExpandedKeysForSearch(node.children, keyword, [...parentKeys, node.key]) : []
    
    if (matchTitle || childKeys.length > 0) {
      if (parentKeys.length > 0) {
        expandedKeys.push(...parentKeys)
      }
      expandedKeys.push(...childKeys)
    }
  }
  
  return [...new Set(expandedKeys)]
}

/**
 * 监听搜索文本变化，自动展开匹配路径
 */
watch(searchText, (newVal) => {
  if (newVal && newVal.trim()) {
    const keysToExpand = getExpandedKeysForSearch(props.treeData, newVal.toLowerCase())
    expandedKeys.value = [...new Set([...expandedKeys.value, ...keysToExpand])]
  }
})

/**
 * 从原始树数据中查找节点
 * @param key 节点 key
 * @returns 原始节点数据
 */
const getOriginalNode = (key: string): SmartTreeNode | undefined => {
  const find = (nodes: SmartTreeNode[]): SmartTreeNode | undefined => {
    for (const node of nodes) {
      if (node.key === key) return node
      if (node.children) {
        const found = find(node.children)
        if (found) return found
      }
    }
    return undefined
  }
  return find(props.treeData)
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

/**
 * 递归过滤树节点
 * @param nodes 节点列表
 * @param keyword 搜索关键词
 */
function filterTree(nodes: SmartTreeNode[], keyword: string): SmartTreeNode[] {
  const result: SmartTreeNode[] = []

  for (const node of nodes) {
    const matchTitle = node.title.toLowerCase().includes(keyword)
    const filteredChildren = node.children ? filterTree(node.children, keyword) : []

    if (matchTitle || filteredChildren.length > 0) {
      result.push({
        ...node,
        children: filteredChildren.length > 0 ? filteredChildren : node.children
      })
    }
  }

  return result
}

/**
 * 高亮搜索文本
 * @param text 原文本
 */
function highlightText(text: string): string {
  if (!searchText.value) return text
  const regex = new RegExp(`(${searchText.value})`, 'gi')
  return text.replace(regex, '<mark style="background: #ffe58f; padding: 0 2px;">$1</mark>')
}

/**
 * 根据文件名获取文件图标类型
 * @param fileName 文件名
 * @returns 图标类型标识
 */
function getFileIconType(fileName: string): string {
  const ext = fileName.toLowerCase().split('.').pop() || ''
  const iconMap: Record<string, string> = {
    pdf: 'pdf',
    doc: 'word',
    docx: 'word',
    xls: 'excel',
    xlsx: 'excel',
    ppt: 'ppt',
    pptx: 'ppt',
    txt: 'text',
    md: 'markdown',
    jpg: 'image',
    jpeg: 'image',
    png: 'image',
    gif: 'image',
    zip: 'zip',
    rar: 'zip',
    mp4: 'video',
    mp3: 'audio'
  }
  return iconMap[ext] || 'file'
}

/**
 * 获取文件图标颜色
 * @param fileName 文件名
 * @returns 颜色值
 */
function getFileIconColor(fileName: string): string {
  const type = getFileIconType(fileName)
  const colorMap: Record<string, string> = {
    pdf: '#ff4d4f',
    word: '#1890ff',
    excel: '#52c41a',
    ppt: '#fa8c16',
    text: '#8c8c8c',
    markdown: '#13c2c2',
    image: '#eb2f96',
    zip: '#722ed1',
    video: '#f5222d',
    audio: '#fa541c',
    file: '#8c8c8c'
  }
  return colorMap[type] || '#8c8c8c'
}

/**
 * 获取状态颜色
 * @param status 状态值
 */
function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    pending: 'default',
    uploading: 'processing',
    processing: 'processing',
    completed: 'success',
    failed: 'error'
  }
  return colors[status] || 'default'
}

/**
 * 获取状态文本
 * @param status 状态值
 */
function getStatusText(status: string): string {
  const texts: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '处理中',
    completed: '已完成',
    failed: '失败'
  }
  return texts[status] || '未知'
}

/**
 * 选择节点回调
 * @param keys 选中的key
 * @param info 选中信息
 */
const onSelect: TreeProps['onSelect'] = (keys, info) => {
  emit('select', keys as string[], info.selectedNodes as SmartTreeNode[])
}

/**
 * 拖拽回调 - 本地更新数据避免回弹
 * @param info 拖拽信息
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
  
  // 创建数据副本
  const data = JSON.parse(JSON.stringify(internalTreeData.value))
  let dragObj: SmartTreeNode | undefined
  
  // 从原位置移除拖拽节点
  const removeNode = (nodes: SmartTreeNode[]): boolean => {
    for (let i = 0; i < nodes.length; i++) {
      if (nodes[i].key === dragNode.key) {
        dragObj = nodes[i]
        nodes.splice(i, 1)
        return true
      }
      const childNodes = nodes[i].children
      if (childNodes && removeNode(childNodes)) {
        return true
      }
    }
    return false
  }
  removeNode(data)
  
  if (!dragObj) return
  
  // dropToGap: true 表示拖到了节点之间的缝隙（平级），false 表示拖到了节点上（放入内部）
  const dropToGap = (info as any).dropToGap
  const pos = String((dropNode as any).pos || '')
  const posParts = pos.split('-')
  const nodeIndex = Number(posParts[posParts.length - 1] || 0)
  const relativeDropPosition = ((info as any).dropPosition as number) - nodeIndex
  
  // 判断目标是否是文件夹
  const isDropNodeFolder = (dropNode as any).dataRef?.isFolder === true
  const shouldInsertInto = !dropToGap && isDropNodeFolder

  if (!dropToGap && !isDropNodeFolder) {
    emit('drop-invalid', 'drop-into-file')
    return
  }
  
  // 插入到新位置
  if (shouldInsertInto) {
    // 放入目标节点内部（作为子节点）
    const insertInto = (nodes: SmartTreeNode[]): boolean => {
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].key === dropNode.key) {
          if (!nodes[i].children) {
            nodes[i].children = []
          }
          const childNodes = nodes[i].children || []
          childNodes.push(dragObj!)
          nodes[i].children = childNodes
          return true
        }
        const childNodes = nodes[i].children
        if (childNodes && insertInto(childNodes)) {
          return true
        }
      }
      return false
    }
    insertInto(data)
  } else {
    // 放在目标节点前后（作为同级节点）
    const insertAt = (nodes: SmartTreeNode[]): boolean => {
      for (let i = 0; i < nodes.length; i++) {
        if (nodes[i].key === dropNode.key) {
          const insertIndex = relativeDropPosition < 0 ? i : i + 1
          nodes.splice(insertIndex, 0, dragObj!)
          return true
        }
        const childNodes = nodes[i].children
        if (childNodes && insertAt(childNodes)) {
          return true
        }
      }
      return false
    }
    insertAt(data)
  }
  
  // 更新内部数据（立即生效，避免回弹）
  internalTreeData.value = data
  
  // 通知父组件
  emit('drop', info)
}

const onNodeDragStart: TreeProps['onDragstart'] = (info) => {
  draggingNodeKey.value = String(info.node?.key || '')
}

const onNodeDragEnd: TreeProps['onDragend'] = () => {
  draggingNodeKey.value = null
}

const onRootDragOver = (e: DragEvent) => {
  if (e.dataTransfer?.types.includes('Files')) return
  e.preventDefault()
}

const onRootDrop = (e: DragEvent) => {
  if (e.dataTransfer?.types.includes('Files')) return
  if (!draggingNodeKey.value) return
  emit('drop-root', draggingNodeKey.value)
  draggingNodeKey.value = null
}

/**
 * 搜索回调
 * @param value 搜索值
 */
const onSearch = () => {
  emit('search', searchText.value)
}

/**
 * 处理文件拖拽进入
 * @param e 拖拽事件
 */
const onFileDragOver = (e: DragEvent) => {
  if (e.dataTransfer?.types.includes('Files')) {
    isDraggingFile.value = true
    e.preventDefault()
    const target = e.target as HTMLElement | null
    const treeNodeElement = target?.closest('.ant-tree-treenode') as HTMLElement | null
    const nodeKey = treeNodeElement?.getAttribute('data-node-key')
    if (!nodeKey) {
      dragOverKey.value = null
      return
    }
    const node = getOriginalNode(nodeKey)
    dragOverKey.value = node?.isFolder ? nodeKey : null
  }
}

/**
 * 处理文件拖拽离开
 * @param e 拖拽事件
 */
const onFileDragLeave = (e: DragEvent) => {
  const rect = (e.currentTarget as HTMLElement).getBoundingClientRect()
  const x = e.clientX
  const y = e.clientY
  if (x < rect.left || x > rect.right || y < rect.top || y > rect.bottom) {
    isDraggingFile.value = false
    dragOverKey.value = null
  }
}

/**
 * 处理文件拖拽放下
 * @param e 拖拽事件
 */
const onFileDrop = (e: DragEvent) => {
  isDraggingFile.value = false
  const files = e.dataTransfer?.files
  if (files && files.length > 0) {
    e.preventDefault()
    const fileArray = Array.from(files)
    // 获取目标文件夹：如果拖到了某个文件夹上，则使用该文件夹，否则为 null（根目录）
    const targetFolder = dragOverKey.value ? getOriginalNode(dragOverKey.value) : null
    emit('file-drop', fileArray, targetFolder as SmartTreeNode | null)
  }
  dragOverKey.value = null
}

/**
 * 获取允许的文件类型描述
 * @returns 文件类型描述文本
 */
const getAllowedFileTypesDesc = (): string => {
  if (!props.allowedFileTypes || props.allowedFileTypes.length === 0) {
    return '所有文件'
  }
  return props.allowedFileTypes.join(', ')
}

/**
 * 展开所有节点
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
 * 收起所有节点
 */
const collapseAll = () => {
  expandedKeys.value = []
}

/**
 * 获取当前选中的节点
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
 * 验证文件类型是否允许上传
 * @param file 文件对象
 * @returns 是否允许上传
 */
const validateFileType = (file: File): boolean => {
  if (!props.allowedFileTypes || props.allowedFileTypes.length === 0) {
    return true
  }
  const fileName = file.name.toLowerCase()
  return props.allowedFileTypes.some(ext => fileName.endsWith(ext.toLowerCase()))
}

// 暴露方法
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

  // 搜索栏
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

  // 树内容区
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

      // 优化树节点样式 - 减少间距
      .ant-tree-treenode {
        padding: 0 !important;
        margin: 0;

        // 减小缩进 - 从默认 24px 改为 10px
        .ant-tree-indent {
          .ant-tree-indent-unit {
            width: 10px;
          }
        }

        // 一级节点减少左侧padding
        &[data-level="0"] {
          > .ant-tree-switcher {
            margin-left: 0;
          }
          > .ant-tree-node-content-wrapper {
            padding-left: 4px !important;
          }
        }
      }

      .ant-tree-node-content-wrapper {
        padding: 0 3px !important;
        border-radius: 4px;
        transition: background 0.2s;
        width: 100%;
        min-width: 0;
        overflow: hidden;

        &:hover {
          background: rgba(0, 0, 0, 0.04);
        }

        &.ant-tree-node-selected {
          background: rgba(24, 144, 255, 0.1);
        }
      }

      .ant-tree-title {
        font-size: 13px;
        display: block;
        width: 100%;
        overflow: hidden;
        min-width: 0;
      }

      // 开关图标样式 - 减小宽度
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

      // 确保树节点内容垂直居中
      .ant-tree-node-content-wrapper {
        height: 100% !important;
        line-height: normal !important;
        display: flex;
        align-items: center;
        padding: 0 2px !important;
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

  // 默认节点样式
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

    // 一级节点减少左侧间距
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

      // 确保标题内的 span 也应用截断
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

  // 空状态
  .tree-empty {
    padding: 32px 0;
    text-align: center;

    .add-root-btn {
      margin-top: 12px;
    }
  }

  // 加载状态
  .tree-loading {
    padding: 16px 0;
    text-align: center;
  }

  // 文件拖拽提示
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
