/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] + EvalFolder[] 转换为 SmartTreeNode[]，基于真实文件夹层级构建树。
 * 树的挂载与排序直接用 @angineer/smartree 的 buildTreeFromFlat（与知识库树同一套工具），
 * 不再自行递归拼树。
 */
import { computed, type Ref } from 'vue'
import { buildTreeFromFlat, type SmartTreeNode } from '@angineer/smartree'
import type { EvalDataset, EvalDatasetCategory, EvalFolder } from '../types/eval'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

/** 判断是否为分类文件夹（知识库评测/SOP评测） */
export const isCategoryFolder = (node: SmartTreeNode): boolean => {
  const key = String(node.key || '')
  return key === 'folder-knowledge' || key === 'folder-sop'
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
  return 'knowledge'
}

export function useEvalDatasetTree(
  datasets: Ref<EvalDataset[]>,
  folders?: Ref<EvalFolder[]>,
) {
  /** 将 datasets 和 folders 转换为树结构（基于真实父子关系；同层文件夹在前、按 sort_order 排序） */
  const treeData = computed<EvalTreeNode[]>(() => {
    const folderNodes: EvalTreeNode[] = (folders?.value || []).map(f => ({
      key: f.folder_id,
      title: f.title,
      isFolder: true,
      selectable: true,
      category: f.category,
      parentId: f.parent_folder_id || undefined,
      sort_order: f.sort_order,
    }))
    const datasetNodes: EvalTreeNode[] = datasets.value.map(item => ({
      key: item.dataset_id,
      title: item.title,
      isLeaf: true,
      isFolder: false,
      questionCount: item.question_count,
      category: item.category,
      parentId: item.folder_id || undefined,
      sort_order: item.sort_order,
    }))
    return buildTreeFromFlat({ folders: folderNodes, items: datasetNodes })
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
