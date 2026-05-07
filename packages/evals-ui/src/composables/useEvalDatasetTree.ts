/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] + EvalFolder[] 转换为 SmartTreeNode[]，基于真实文件夹层级构建树。
 */
import { computed, type Ref } from 'vue'
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDataset, EvalDatasetCategory, EvalFolder } from '../types/eval'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

/** 判断是否为分类文件夹（知识库评测/SOP评测/全链路评测） */
export const isCategoryFolder = (node: SmartTreeNode): boolean => {
  const key = String(node.key || '')
  return key === 'folder-knowledge' || key === 'folder-sop' || key === 'folder-full_chain'
}

/** 判断是否为后端持久化文件夹节点 */
export const isPersistedFolder = (node: SmartTreeNode): boolean => {
  return !!(node.key && String(node.key).startsWith('folder-'))
}

/** 从节点 key 或属性中提取 category */
export const getCategoryFromNode = (node: SmartTreeNode): EvalDatasetCategory => {
  if ((node as EvalTreeNode).category) return (node as EvalTreeNode).category!
  const key = String(node.key || '')
  if (key === 'folder-knowledge') return 'knowledge'
  if (key === 'folder-sop') return 'sop'
  if (key === 'folder-full_chain') return 'full_chain'
  return 'knowledge'
}

export function useEvalDatasetTree(
  datasets: Ref<EvalDataset[]>,
  folders?: Ref<EvalFolder[]>,
) {
  /** 将数据集转换为树节点 */
  const datasetToNode = (item: EvalDataset): SmartTreeNode => ({
    key: item.dataset_id,
    title: item.title,
    isLeaf: true,
    isFolder: false,
    questionCount: item.question_count,
    category: item.category,
  })

  /** 递归构建指定父节点下的子树（子文件夹 + 数据集） */
  const buildChildren = (
    parentId: string,
    allFolders: EvalFolder[],
    datasetsByFolder: Record<string, EvalDataset[]>,
  ): SmartTreeNode[] => {
    const childFolders = allFolders
      .filter(f => (f.parent_folder_id || '') === parentId)
      .sort((a, b) => a.sort_order - b.sort_order)

    return childFolders.map(f => ({
      key: f.folder_id,
      title: f.title,
      isFolder: true as const,
      selectable: true,
      category: f.category,
      children: [
        ...buildChildren(f.folder_id, allFolders, datasetsByFolder),
        ...(datasetsByFolder[f.folder_id] || [])
          .sort((a, b) => a.sort_order - b.sort_order)
          .map(datasetToNode),
      ],
    }))
  }

  /** 将 datasets 和 folders 转换为树结构（基于真实父子关系） */
  const treeData = computed<SmartTreeNode[]>(() => {
    const allFolders = folders?.value || []

    const datasetsByFolder: Record<string, EvalDataset[]> = {}
    for (const ds of datasets.value) {
      const key = ds.folder_id || '__root__'
      if (!datasetsByFolder[key]) datasetsByFolder[key] = []
      datasetsByFolder[key].push(ds)
    }

    const rootFolders = allFolders
      .filter(f => !f.parent_folder_id || f.parent_folder_id === '')
      .sort((a, b) => a.sort_order - b.sort_order)

    return [
      ...rootFolders.map(f => ({
        key: f.folder_id,
        title: f.title,
        isFolder: true as const,
        selectable: true,
        category: f.category,
        children: [
          ...buildChildren(f.folder_id, allFolders, datasetsByFolder),
          ...(datasetsByFolder[f.folder_id] || [])
            .sort((a, b) => a.sort_order - b.sort_order)
            .map(datasetToNode),
        ],
      })),
      ...(datasetsByFolder['__root__'] || [])
        .filter(ds => !ds.folder_id || ds.folder_id === '')
        .sort((a, b) => a.sort_order - b.sort_order)
        .map(datasetToNode),
    ]
  })

  /** 默认展开所有节点 */
  const defaultExpandedKeys = computed(() =>
    treeData.value.map(n => n.key)
  )

  return {
    treeData,
    defaultExpandedKeys,
    isCategoryFolder,
    isPersistedFolder,
    getCategoryFromNode,
  }
}
