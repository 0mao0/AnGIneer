/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] + EvalFolder[] 转换为 SmartTreeNode[]，提供分组、展开等计算属性。
 */
import { computed, type Ref } from 'vue'
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDataset, EvalDatasetCategory, EvalFolder } from '../types/eval'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

const ALL_CATEGORIES: { key: EvalDatasetCategory; label: string }[] = [
  { key: 'knowledge', label: '知识库评测' },
  { key: 'sop', label: 'SOP 评测' },
  { key: 'full_chain', label: '全链路评测' },
]

/** 判断是否为虚拟分组节点（按类别自动聚合的文件夹） */
export const isGroupNode = (node: SmartTreeNode): boolean => {
  return !!(node.key && String(node.key).startsWith('group-'))
}

/** 判断是否为后端持久化文件夹节点 */
export const isPersistedFolder = (node: SmartTreeNode): boolean => {
  return !!(node.key && String(node.key).startsWith('folder-'))
}

/** 从 group 节点 key 中提取 category */
export const getCategoryFromGroupKey = (key: string): EvalDatasetCategory => {
  return key.replace('group-', '') as EvalDatasetCategory
}

/** 从节点 key 或属性中提取 category */
export const getCategoryFromNode = (node: SmartTreeNode): EvalDatasetCategory => {
  if (isGroupNode(node)) return getCategoryFromGroupKey(String(node.key))
  if ((node as EvalTreeNode).category) return (node as EvalTreeNode).category!
  return 'knowledge'
}

/** 获取文件夹在分组中的父 key */
const getFolderParentKey = (folder: EvalFolder): string => {
  if (folder.parent_folder_id && folder.parent_folder_id.startsWith('folder-')) {
    return folder.parent_folder_id
  }
  return `group-${folder.category}`
}

export function useEvalDatasetTree(
  datasets: Ref<EvalDataset[]>,
  folders?: Ref<EvalFolder[]>,
) {
  /** 递归构建指定父节点下的文件夹子树 */
  const buildFolderTree = (parentKey: string, category: EvalDatasetCategory): SmartTreeNode[] => {
    const childFolders = (folders?.value || [])
      .filter(f => getFolderParentKey(f) === parentKey && f.category === category)
    return childFolders
      .sort((a, b) => a.sort_order - b.sort_order)
      .map(f => ({
        key: f.folder_id,
        title: f.title,
        isFolder: true as const,
        selectable: true,
        category: f.category,
        children: buildFolderTree(f.folder_id, category),
      }))
  }

  /** 将 datasets 按类别和文件夹分组并转换为树结构 */
  const treeData = computed<SmartTreeNode[]>(() => {
    const groups: Record<string, EvalDataset[]> = {}
    for (const ds of datasets.value) {
      const cat = ds.category || 'knowledge'
      if (!groups[cat]) groups[cat] = []
      groups[cat].push(ds)
    }

    return ALL_CATEGORIES.map(({ key, label }) => ({
      key: `group-${key}`,
      title: label,
      isFolder: true,
      selectable: false,
      category: key,
      children: [
        ...buildFolderTree(`group-${key}`, key),
        ...(groups[key] || [])
          .filter(ds => !ds.folder_id || ds.folder_id === '')
          .sort((a, b) => a.sort_order - b.sort_order)
          .map(item => ({
            key: item.dataset_id,
            title: item.title,
            isLeaf: true,
            isFolder: false,
            questionCount: item.question_count,
            category: item.category,
          })),
      ],
    }))
  })

  /** 默认展开所有分组节点 */
  const defaultExpandedKeys = computed(() =>
    treeData.value.map(n => n.key)
  )

  return {
    treeData,
    defaultExpandedKeys,
    isGroupNode,
    isPersistedFolder,
    getCategoryFromGroupKey,
    getCategoryFromNode,
  }
}
