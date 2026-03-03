<template>
  <!-- 通用智能树组件 - 支持搜索、自定义操作按钮和灵活的数据结构 -->
  <div class="smart-tree" :class="{ 'dark-mode': isDark }">
    <!-- 搜索栏 -->
    <div v-if="showSearch" class="tree-search">
      <a-input-search
        v-model:value="searchText"
        :placeholder="searchPlaceholder"
        size="small"
        allow-clear
        @search="onSearch"
      />
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
      >
        <template #title="{ title, key, ...nodeData }">
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
                    <FileOutlined v-else />
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
                        <EditOutlined class="action-icon" @click="$emit('rename', getOriginalNode(key))" />
                      </a-tooltip>
                      <a-tooltip title="添加子文件夹">
                        <FolderAddOutlined class="action-icon" @click="$emit('add-folder', getOriginalNode(key))" />
                      </a-tooltip>
                      <a-tooltip v-if="allowAddFile" title="添加文件">
                        <FileAddOutlined class="action-icon" @click="$emit('add-file', getOriginalNode(key))" />
                      </a-tooltip>
                      <a-tooltip title="删除">
                        <DeleteOutlined class="action-icon delete" @click="$emit('delete', getOriginalNode(key))" />
                      </a-tooltip>
                    </template>
                    <!-- 文件操作 -->
                    <template v-else>
                      <a-tooltip title="重命名">
                        <EditOutlined class="action-icon" @click="$emit('rename', getOriginalNode(key))" />
                      </a-tooltip>
                      <a-tooltip title="查看">
                        <EyeOutlined class="action-icon" @click="$emit('view', getOriginalNode(key))" />
                      </a-tooltip>
                      <a-tooltip title="删除">
                        <DeleteOutlined class="action-icon delete" @click="$emit('delete', getOriginalNode(key))" />
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

      <!-- 空状态 -->
      <div v-else-if="!loading" class="tree-empty">
        <slot name="empty">
          <a-empty :description="searchText ? '无匹配结果' : emptyText" />
        </slot>
      </div>

      <!-- 加载状态 -->
      <div v-if="loading" class="tree-loading">
        <a-spin size="small" />
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
  EditOutlined,
  FolderAddOutlined,
  FileAddOutlined,
  DeleteOutlined,
  EyeOutlined
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
  showIcon: true,
  showStatus: true,
  showLine: false,
  draggable: false,
  allowAddFile: true,
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
  'add-folder': [node: SmartTreeNode]
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
}>()

// 主题
const { isDark } = useTheme()

// 搜索文本
const searchText = ref('')

// 展开和选中的keys
const expandedKeys = ref<string[]>(props.defaultExpandedKeys)
const selectedKeys = ref<string[]>(props.defaultSelectedKeys)

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
  if (!searchText.value) return props.treeData
  return filterTree(props.treeData, searchText.value.toLowerCase())
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
 * 拖拽回调
 * @param info 拖拽信息
 */
const onDrop: TreeProps['onDrop'] = (info) => {
  emit('drop', info)
}

/**
 * 搜索回调
 * @param value 搜索值
 */
const onSearch = (value: string) => {
  searchText.value = value
  emit('search', value)
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

// 暴露方法
defineExpose({
  expandAll,
  collapseAll,
  getSelectedNodes,
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
  }

  // 搜索栏
  .tree-search {
    padding: 8px 12px;
    border-bottom: 1px solid rgba(0, 0, 0, 0.06);
    flex-shrink: 0;

    :deep(.ant-input-search) {
      .ant-input {
        font-size: 13px;
      }
    }
  }

  // 树内容区
  .tree-content {
    flex: 1;
    overflow: auto;
    padding: 4px 0;

    :deep(.ant-tree) {
      background: transparent;

      // 优化树节点样式 - 减少左侧缩进
      .ant-tree-treenode {
        padding: 2px 0;
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
            margin-left: -2px;
          }
          > .ant-tree-node-content-wrapper {
            padding-left: 2px;
          }
        }
      }

      .ant-tree-node-content-wrapper {
        padding: 2px 6px;
        border-radius: 4px;
        transition: background 0.2s;

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
      }

      // 开关图标样式 - 减小宽度
      .ant-tree-switcher {
        width: 14px;
        height: 24px;
        line-height: 24px;
      }
    }
  }

  // 默认节点样式
  .tree-node-default {
    display: flex;
    align-items: center;
    width: 100%;
    gap: 4px;
    position: relative; // 为绝对定位的操作按钮提供参考

    &.is-folder {
      font-weight: 500;
    }

    // 一级节点减少左侧间距
    &.level-0 {
      margin-left: -4px;
    }

    .node-icon {
      flex-shrink: 0;
      font-size: 14px;
      color: #8c8c8c;

      .anticon-folder {
        color: #faad14;
      }

      .anticon-file {
        color: #8c8c8c;
      }
    }

    .node-title {
      flex: 1;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
      min-width: 0;

      mark {
        border-radius: 2px;
      }
    }

    .node-status {
      flex-shrink: 0;
      // 状态标签也跟随在标题后面，但会被操作按钮覆盖
      margin-right: 4px;

      :deep(.ant-tag) {
        font-size: 10px;
        padding: 0 4px;
        line-height: 16px;
        margin: 0;
      }
    }

    .node-actions {
      display: flex;
      align-items: center;
      gap: 2px;
      flex-shrink: 0;
      opacity: 0;
      transition: opacity 0.2s;
      // 相对定位，跟随在内容后面，而不是固定在右侧
      position: relative;
      margin-left: auto;
      background: var(--bg-color, #fff);
      padding-left: 4px;

      .action-icon {
        font-size: 12px;
        color: #8c8c8c;
        cursor: pointer;
        padding: 2px;
        border-radius: 3px;
        transition: all 0.2s;

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
  }

  // 加载状态
  .tree-loading {
    padding: 16px 0;
    text-align: center;
  }
}
</style>
