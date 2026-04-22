/**
 * 知识树管理 Composable
 * 提供知识树的状态管理和操作方法
 */
import { ref, computed } from 'vue'
import type { KnowledgeTreeNode } from '../types/tree'
export type { KnowledgeTreeNode } from '../types/tree'

// 上传任务类型
export interface UploadTask {
  uid: string
  name: string
  progress: number
  status: 'uploading' | 'processing' | 'completed' | 'failed'
  file?: File
  nodeId?: string
  folderId?: string
}

export function useKnowledgeTree() {
  // 状态
  const treeData = ref<KnowledgeTreeNode[]>([])
  const selectedKeys = ref<string[]>([])
  const expandedKeys = ref<string[]>([])
  const selectedNode = ref<KnowledgeTreeNode | null>(null)
  const uploadTasks = ref<UploadTask[]>([])

  // 计算属性
  const folderTreeData = computed(() => {
    const convert = (nodes: KnowledgeTreeNode[]): any[] =>
      nodes
        .filter(n => n.isFolder)
        .map(n => ({
          value: n.key,
          title: n.title,
          children: n.children ? convert(n.children) : []
        }))
    return convert(treeData.value)
  })

  const hasData = computed(() => treeData.value.length > 0)

  // 构建树结构
  const buildTree = (nodes: any[]): KnowledgeTreeNode[] => {
    const nodeMap = new Map<string, KnowledgeTreeNode>()
    const roots: KnowledgeTreeNode[] = []

    nodes.forEach(n => {
      nodeMap.set(n.id, {
        key: n.id,
        title: n.title,
        isFolder: n.type === 'folder',
        visible: n.visible,
        status: n.status || 'pending',
        parentId: n.parent_id,
        filePath: n.file_path,
        file_path: n.file_path,
        parseProgress: n.parse_progress || 0,
        parseStage: n.parse_stage || '',
        parseError: n.parse_error || '',
        parseTaskId: n.parse_task_id || '',
        strategy: n.strategy || 'doc_blocks_graph_v1'
      })
    })

    nodes.forEach(n => {
      const node = nodeMap.get(n.id)!
      if (n.parent_id && nodeMap.has(n.parent_id)) {
        const parent = nodeMap.get(n.parent_id)!
        if (!parent.children) parent.children = []
        parent.children.push(node)
      } else {
        roots.push(node)
      }
    })

    return roots
  }

  // 查找节点
  const findNode = (nodes: KnowledgeTreeNode[], key: string): KnowledgeTreeNode | null => {
    for (const node of nodes) {
      if (node.key === key) return node
      if (node.children) {
        const found = findNode(node.children, key)
        if (found) return found
      }
    }
    return null
  }

  // 获取子节点数量
  const getChildCount = (parentId: string, type: 'folder' | 'document'): number => {
    const parent = findNode(treeData.value, parentId)
    if (!parent || !parent.children) return 0
    return parent.children.filter(c => (type === 'folder' ? c.isFolder : !c.isFolder)).length
  }

  // 获取文件夹名称
  const getFolderName = (folderId: string): string => {
    const folder = findNode(treeData.value, folderId)
    return folder?.title || '根目录'
  }

  // 选择节点
  const selectNode = (key: string) => {
    selectedKeys.value = [key]
    selectedNode.value = findNode(treeData.value, key)
  }

  // 更新节点状态
  const updateNodeStatus = (key: string, status: KnowledgeTreeNode['status']) => {
    const node = findNode(treeData.value, key)
    if (node) {
      node.status = status
    }
  }

  // 添加上传任务
  const addUploadTask = (task: UploadTask) => {
    uploadTasks.value.push(task)
  }

  // 更新上传任务
  const updateUploadTask = (uid: string, updates: Partial<UploadTask>) => {
    const task = uploadTasks.value.find(t => t.uid === uid)
    if (task) {
      Object.assign(task, updates)
    }
  }

  // 设置树数据
  const setTreeData = (nodes: KnowledgeTreeNode[]) => {
    treeData.value = nodes
  }

  return {
    // 状态
    treeData,
    selectedKeys,
    expandedKeys,
    selectedNode,
    uploadTasks,
    // 计算属性
    folderTreeData,
    hasData,
    // 方法
    buildTree,
    findNode,
    getChildCount,
    getFolderName,
    selectNode,
    updateNodeStatus,
    addUploadTask,
    updateUploadTask,
    setTreeData
  }
}
