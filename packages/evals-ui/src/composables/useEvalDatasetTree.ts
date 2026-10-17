/**
 * 评测数据集树数据转换 composable。
 * 将 EvalDataset[] + EvalFolder[] 转换为 SmartTreeNode[]，基于真实文件夹层级构建树。
 * 树的挂载与排序直接用 @angineer/smartree 的 buildTreeFromFlat（与知识库树同一套工具），
 * 不再自行递归拼树。
 */
import { computed, unref, type Ref } from 'vue'
import { buildTreeFromFlat, cleanTitleDisplay, extractTitleNumber } from '@angineer/smartree/utils/tree'
import type { SmartTreeNode } from '@angineer/smartree'
import type { EvalDataset, EvalDatasetCategory, EvalFolder } from '../types/eval'

export interface EvalTreeNode extends SmartTreeNode {
  questionCount?: number
  category?: EvalDatasetCategory
}

/** 判断是否为分类文件夹（知识库评测/SOP评测，种子目录固定 key） */
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

/** 从标题提取「编号+【】前缀」里的编号（「1【金融】…」→ 1，「12·GDP…」→ 12；「【法律】…」→ null） */
export { extractTitleNumber, cleanTitleDisplay }

export interface EvalTreeOptions {
  /** 标题编号前缀参与排序（默认 true）：「1【金融】…」按编号置前，「【法律】…」这类无编号前缀的排末尾 */
  numberedFirst?: Ref<boolean> | boolean
  /** 标题展示净化（默认 false）：「1【金融】FinanceBench…」→「FinanceBench 150题」，只改渲染显示，不改存储标题 */
  stripTitleNumberPrefix?: Ref<boolean> | boolean
}

export function useEvalDatasetTree(
  datasets: Ref<EvalDataset[]>,
  folders?: Ref<EvalFolder[]>,
  options: EvalTreeOptions = {},
) {
  const numberedFirst = computed(() => unref(options.numberedFirst ?? true))
  const stripTitleNumberPrefix = computed(() => unref(options.stripTitleNumberPrefix ?? false))

  /** 树显示标题：默认原样；开关开启后净化「编号+【】前缀」（仅影响显示与排序键） */
  const displayTitle = (title: string): string =>
    stripTitleNumberPrefix.value ? cleanTitleDisplay(title) : title

  /** 将 datasets 和 folders 转换为树结构（基于真实父子关系）：
   *  numberedFirst 开启时编号前缀参与排序（含拖拽落位回写后仍按编号插回原位），关闭时维持 sort_order 优先 */
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
      displayTitle: displayTitle(item.title),
      isLeaf: true,
      isFolder: false,
      questionCount: item.question_count,
      category: item.category,
      parentId: item.folder_id || undefined,
      sort_order: item.sort_order,
    }))
    return buildTreeFromFlat({
      folders: folderNodes,
      items: datasetNodes,
      numberedFirst: numberedFirst.value,
      // 净化开启时按净化后的显示名排序；关闭时按原标题拼音兜底
      compareTitle: (node: EvalTreeNode) => node.displayTitle || node.title,
    })
  })

  return {
    treeData,
    isCategoryFolder,
    isPersistedFolder,
    getCategoryFromNode,
  }
}
