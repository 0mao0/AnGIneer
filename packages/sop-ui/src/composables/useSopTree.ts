/**
 * 经验库树 Composable
 * 提供经验库树数据的加载、查找、选中状态管理与 CRUD 操作
 */
import { ref } from 'vue'
import type { DropEvent } from '@angineer/ui-kit'
import type { SOPTreeNode, SopListItem, SopFolder, SopData } from '../types/sop'
import { sopApi } from './useSopApi'

export type { SOPTreeNode } from '../types/sop'

/** 按排序号和标题排序节点。 */
const sortByOrder = <T extends { sort_order?: number; sortOrder?: number; title?: string; name_zh?: string }>(items: T[]): T[] => {
  return [...items].sort((a, b) => {
    const aOrder = typeof a.sort_order === 'number'
      ? a.sort_order
      : (typeof a.sortOrder === 'number' ? a.sortOrder : Number.MAX_SAFE_INTEGER)
    const bOrder = typeof b.sort_order === 'number'
      ? b.sort_order
      : (typeof b.sortOrder === 'number' ? b.sortOrder : Number.MAX_SAFE_INTEGER)
    if (aOrder !== bOrder) {
      return aOrder - bOrder
    }
    const aTitle = a.title || a.name_zh || ''
    const bTitle = b.title || b.name_zh || ''
    return aTitle.localeCompare(bTitle, 'zh-CN')
  })
}

/** 将 API 返回的 SOP 列表和文件夹构建为树结构 */
function buildTreeFromApi(sops: SopListItem[], folders: SopFolder[]): SOPTreeNode[] {
  const folderMap = new Map<string, SOPTreeNode>()

  folders.forEach((folder) => {
    folderMap.set(folder.folder_id, {
      key: folder.folder_id,
      title: folder.title,
      isFolder: true,
      category: 'sop',
      parentId: folder.parent_folder_id || undefined,
      sortOrder: folder.sort_order,
      children: [],
    })
  })

  sortByOrder(folders).forEach((folder) => {
    const node = folderMap.get(folder.folder_id)!
    if (folder.parent_folder_id && folderMap.has(folder.parent_folder_id)) {
      folderMap.get(folder.parent_folder_id)!.children!.push(node)
    }
  })

  const sopNodes: SOPTreeNode[] = sortByOrder(sops).map((sop) => ({
    key: sop.id,
    title: sop.name_zh || sop.id,
    description: sop.description,
    category: 'sop',
    isFolder: false,
    isLeaf: true,
    parentId: sop.folder_id || undefined,
    sortOrder: sop.sort_order,
  }))

  sopNodes.forEach((node) => {
    if (node.parentId && folderMap.has(node.parentId)) {
      folderMap.get(node.parentId)!.children!.push(node)
    }
  })

  const normalizeChildren = (nodes: SOPTreeNode[]): SOPTreeNode[] => {
    const foldersOnly = sortByOrder(nodes.filter((node) => node.isFolder))
    const filesOnly = sortByOrder(nodes.filter((node) => !node.isFolder))
    foldersOnly.forEach((node) => {
      node.children = normalizeChildren(node.children || [])
    })
    return [...foldersOnly, ...filesOnly]
  }

  const rootFolders = sortByOrder(
    folders
      .filter((folder) => !folder.parent_folder_id || !folderMap.has(folder.parent_folder_id))
      .map((folder) => folderMap.get(folder.folder_id)!)
  )
  const rootFiles = sortByOrder(sopNodes.filter((node) => !node.parentId || !folderMap.has(node.parentId)))

  return normalizeChildren([...rootFolders, ...rootFiles])
}

/** 管理经验库树状态 */
export function useSopTree() {
  const treeData = ref<SOPTreeNode[]>([])
  const selectedNode = ref<SOPTreeNode | null>(null)
  const currentSopData = ref<SopData | null>(null)
  const loading = ref(false)

  /** 从后端 API 加载树数据 */
  const fetchTreeFromApi = async (): Promise<SOPTreeNode[]> => {
    loading.value = true
    try {
      const [sopsResult, foldersResult] = await Promise.all([
        sopApi.listSops(),
        sopApi.getFolders(),
      ])
      treeData.value = buildTreeFromApi(sopsResult.sops || [], foldersResult.folders || [])
      return treeData.value
    } catch (error) {
      console.error('加载 SOP 树失败:', error)
      treeData.value = []
      return []
    } finally {
      loading.value = false
    }
  }

  /** 获取指定 SOP 的完整数据 */
  const fetchSopDetail = async (sopId: string): Promise<SopData | null> => {
    try {
      const data = await sopApi.getSop(sopId)
      currentSopData.value = data
      return data
    } catch (error) {
      console.error(`加载 SOP ${sopId} 详情失败:`, error)
      return null
    }
  }

  /** 创建文件夹 */
  const createFolder = async (title: string, parentFolderId?: string) => {
    try {
      await sopApi.createFolder({ title, parent_folder_id: parentFolderId })
    } catch (error) {
      console.error('创建文件夹失败:', error)
      throw error
    }
  }

  /** 创建空白 SOP。 */
  const createEmptySop = async (name: string, folderId?: string) => {
    const trimmedName = name.trim()
    const result = await sopApi.createSop({
      name_zh: trimmedName,
      name_en: trimmedName,
      description: '',
      folder_id: folderId,
      steps: [],
    })
    return result.id
  }

  /** 导入 Markdown 文件并创建 SOP。 */
  const importSopJson = async (file: File, folderId?: string) => {
    const result = await sopApi.importSop(file, folderId)
    return result.id
  }

  /** 重命名 SOP。 */
  const renameSop = async (sopId: string, name: string) => {
    await sopApi.updateSopMeta(sopId, { name_zh: name.trim(), name_en: name.trim() })
  }

  /** 更新 SOP 所在文件夹与同级顺序。 */
  const moveNode = async (event: DropEvent) => {
    const { targetParentKey, siblings } = event
    await Promise.all(
      siblings.map((item, index) => {
        if (item.isFolder) {
          return sopApi.updateFolder(item.key, {
            parent_folder_id: targetParentKey || null,
            title: item.title,
            sort_order: index,
          })
        }
        return sopApi.updateSopMeta(item.key, {
          folder_id: targetParentKey || null,
          sort_order: index,
        })
      })
    )
  }

  /** 将节点移动到根目录。 */
  const moveNodeToRoot = async (dragNodeKey: string) => {
    const node = findNode(treeData.value, dragNodeKey)
    if (!node) return
    if (node.isFolder) {
      const rootFolders = treeData.value.filter((item) => item.isFolder && item.key !== dragNodeKey)
      await Promise.all([
        ...rootFolders.map((item, index) => sopApi.updateFolder(item.key, { sort_order: index })),
        sopApi.updateFolder(dragNodeKey, { parent_folder_id: null, sort_order: rootFolders.length }),
      ])
      return
    }
    const rootFiles = treeData.value.filter((item) => !item.isFolder && item.key !== dragNodeKey)
    await Promise.all([
      ...rootFiles.map((item, index) => sopApi.updateSopMeta(item.key, { folder_id: null, sort_order: index })),
      sopApi.updateSopMeta(dragNodeKey, { folder_id: null, sort_order: rootFiles.length }),
    ])
  }

  /** 删除 SOP */
  const deleteSop = async (sopId: string) => {
    try {
      await sopApi.deleteSop(sopId)
      if (selectedNode.value?.key === sopId) {
        selectedNode.value = null
        currentSopData.value = null
      }
      await fetchTreeFromApi()
    } catch (error) {
      console.error(`删除 SOP ${sopId} 失败:`, error)
      throw error
    }
  }

  /** 设置经验库树数据 */
  const setTreeData = (nodes: SOPTreeNode[]) => {
    treeData.value = nodes
  }

  /** 递归查找指定经验库节点 */
  const findNode = (nodes: SOPTreeNode[], key: string): SOPTreeNode | null => {
    for (const node of nodes) {
      if (node.key === key) return node
      if (node.children?.length) {
        const found = findNode(node.children, key)
        if (found) return found
      }
    }
    return null
  }

  /** 记录当前选中的经验库节点 */
  const setSelectedNode = (node: SOPTreeNode | null) => {
    selectedNode.value = node
  }

  return {
    treeData,
    selectedNode,
    currentSopData,
    loading,
    setTreeData,
    fetchTreeFromApi,
    fetchSopDetail,
    createFolder,
    createEmptySop,
    importSopJson,
    renameSop,
    moveNode,
    moveNodeToRoot,
    deleteSop,
    findNode,
    setSelectedNode,
  }
}
