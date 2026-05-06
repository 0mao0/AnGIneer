/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] 转换为 SmartTreeNode[]，提供分组、展开等计算属性。
 */
import { computed, type Ref } from 'vue'
import type { SmartTreeNode } from '@angineer/ui-kit'
import type { EvalDataset, EvalDatasetCategory } from '../types/eval'

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

/** 从 group 节点 key 中提取 category */
export const getCategoryFromGroupKey = (key: string): EvalDatasetCategory => {
  return key.replace('group-', '') as EvalDatasetCategory
}

export function useEvalDatasetTree(datasets: Ref<EvalDataset[]>) {
  /** 将 datasets 按类别分组并转换为树结构 */
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
      children: (groups[key] || []).map(item => ({
        key: item.dataset_id,
        title: item.title,
        isLeaf: true,
        isFolder: false,
        questionCount: item.question_count,
        category: item.category,
      })),
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
    getCategoryFromGroupKey,
  }
}
