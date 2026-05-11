/**
 * 经验库树 Composable
 * 提供经验库树数据的加载、查找、选中状态管理与 CRUD 操作
 */
import { ref } from 'vue'
import type { SOPTreeNode, SopListItem, SopFolder, SopData } from '../types/sop'
import { sopApi } from './useSopApi'

export type { SOPTreeNode } from '../types/sop'

/** 将 API 返回的 SOP 列表和文件夹构建为树结构 */
function buildTreeFromApi(sops: SopListItem[], folders: SopFolder[]): SOPTreeNode[] {
  const folderNodes: SOPTreeNode[] = folders.map((f) => ({
    key: f.folder_id,
    title: f.title,
    isFolder: true,
    category: 'sop',
    children: [],
  }))

  const sopNodes: SOPTreeNode[] = sops.map((s) => ({
    key: s.id,
    title: s.name_zh || s.id,
    description: s.description,
    category: 'sop',
    isFolder: false,
    isLeaf: true,
    parentId: s.folder_id || undefined,
  }))

  for (const sopNode of sopNodes) {
    const parent = folderNodes.find((f) => f.key === sopNode.parentId)
    if (parent) {
      parent.children!.push(sopNode)
    }
  }

  const rootNodes = folderNodes.filter((f) => {
    const folder = folders.find((fo) => fo.folder_id === f.key)
    return !folder?.parent_folder_id
  })

  const unparentedSops = sopNodes.filter((s) => !s.parentId || !folderNodes.find((f) => f.key === s.parentId))
  if (unparentedSops.length > 0) {
    rootNodes.push(...unparentedSops)
  }

  return rootNodes
}

/** 管理经验库树状态 */
export function useSopTree() {
  const treeData = ref<SOPTreeNode[]>([])
  const selectedNode = ref<SOPTreeNode | null>(null)
  const currentSopData = ref<SopData | null>(null)
  const loading = ref(false)

  /** 从后端 API 加载树数据 */
  const fetchTreeFromApi = async () => {
    loading.value = true
    try {
      const [sopsResult, foldersResult] = await Promise.all([
        sopApi.listSops(),
        sopApi.getFolders(),
      ])
      treeData.value = buildTreeFromApi(sopsResult.sops || [], foldersResult.folders || [])
    } catch (error) {
      console.error('加载 SOP 树失败:', error)
      treeData.value = []
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
      await fetchTreeFromApi()
    } catch (error) {
      console.error('创建文件夹失败:', error)
      throw error
    }
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
    deleteSop,
    findNode,
    setSelectedNode,
  }
}
