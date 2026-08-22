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

  // 构建树结构：libraries 提供库根虚拟节点（key 约定 lib:{id}），各库根级节点挂到其下。
  // 历史遗留的根级『默认/管理员上传』文件夹展平（不显示），其内容直接挂库根。
  const buildTree = (nodes: any[], libraries: any[] = []): KnowledgeTreeNode[] => {
    const nodeMap = new Map<string, KnowledgeTreeNode>()
    const roots: KnowledgeTreeNode[] = []

    nodes.forEach(n => {
      nodeMap.set(n.id, {
        key: n.id,
        title: n.title,
        isFolder: n.type === 'folder',
        visible: n.visible,
        libraryId: n.library_id,
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

    // 所有知识库都生成库根虚拟节点（含空库），保证新建库在树中可见
    for (const lib of libraries) {
      roots.push({
        key: `lib:${lib.id}`,
        title: lib.name || lib.id,
        isFolder: true,
        visible: true,
        libraryId: lib.id,
        status: 'pending',
        parentId: '',
        filePath: '',
        file_path: '',
        parseProgress: 0,
        parseStage: '',
        parseError: '',
        parseTaskId: '',
        strategy: 'doc_blocks_graph_v1',
        children: []
      })
    }

    // 展平：历史遗留的库根级文件夹不显示，内容挂库根。
    // 规则：根级 folder 且（title 为默认/管理员上传，或 title 与库名相同/互为前后缀，或库名去掉常见后缀词后与 title 相同）
    const FLATTEN_TITLES = new Set(['默认', '管理员上传'])
    const libNames = new Map(libraries.map(l => [l.id, String(l.name || '')]))
    // 库名去尾部常见后缀词：知识库/文件夹/目录/库
    const stripSuffix = (s: string): string =>
      ['知识库', '文件夹', '目录', '库'].reduce(
        (acc, suf) => (acc.length > suf.length && acc.endsWith(suf) ? acc.slice(0, -suf.length) : acc),
        s
      )
    const isLegacyFolder = (n: any): boolean => {
      if (!n.parent_id && n.type === 'folder') {
        if (FLATTEN_TITLES.has(n.title)) return true
        const libName = libNames.get(n.library_id) || ''
        if (libName.length >= 2) {
          const stripped = stripSuffix(libName)
          if (stripped.length >= 2 && (n.title === stripped || n.title.startsWith(stripped) || stripped.startsWith(n.title))) return true
          if (n.title === libName || n.title.startsWith(libName) || libName.startsWith(n.title)) return true
        }
      }
      return false
    }
    const flattenIds = new Set<string>(
      nodes.filter(isLegacyFolder).map(n => n.id)
    )

    // 向上解析可见父级（跳过被展平的节点）
    const resolveParent = (parentId: string): KnowledgeTreeNode | null => {
      let pid: string | undefined = parentId
      while (pid && flattenIds.has(pid)) {
        pid = nodeMap.get(pid)?.parentId || undefined
      }
      return pid && nodeMap.has(pid) ? nodeMap.get(pid)! : null
    }

    const ensureChildren = (node: KnowledgeTreeNode) => {
      if (!node.children) node.children = []
      return node.children
    }

    nodes.forEach(n => {
      const node = nodeMap.get(n.id)!
      if (flattenIds.has(n.id)) return
      const parent = resolveParent(n.parent_id)
      if (parent) {
        ensureChildren(parent).push(node)
      } else {
        const libRoot = roots.find(r => r.key === `lib:${n.library_id}`)
        if (libRoot) {
          ensureChildren(libRoot).push(node)
        } else {
          roots.push(node)
        }
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
