/**
 * SOP 资源适配器
 * 将 SOP 领域对象转换为通用 ResourceNode，用于工作台标签页打开等场景。
 */
import type { SOPTreeNode } from '../types/sop'
import type { ResourceNode } from '@angineer/docs-ui'

export interface SopItem {
  id: string
  title: string
  description?: string
}

type SopResourceLike = SopItem | Pick<SOPTreeNode, 'key' | 'title' | 'description'>

/**
 * 将 SOP 条目或树节点转换为通用资源节点。
 */
export const createResourceNodeFromSop = (sop: SopResourceLike): ResourceNode => {
  const sopId = 'id' in sop ? sop.id : sop.key

  return {
    id: sopId,
    title: sop.title,
    resourceType: 'sop',
    description: sop.description
  }
}
