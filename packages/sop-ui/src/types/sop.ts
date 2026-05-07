/**
 * sop-ui 领域类型定义。
 * SmartTreeNode 从 @angineer/ui-kit 统一导出，不在本地重复定义。
 */
import type { SmartTreeNode } from '@angineer/ui-kit'

export interface SOPTreeNode extends SmartTreeNode {
  isFolder: boolean
  description?: string
  category?: string
  children?: SOPTreeNode[]
}
