/**
 * 经验库树 Composable
 * 提供经验库树数据的默认构造、查找与选中状态管理
 */
import { ref } from 'vue'
import type { SOPTreeNode } from '../types/tree'

export type { SOPTreeNode } from '../types/tree'

/**
 * 创建默认的经验库树数据。
 */
const createDefaultSopTree = (): SOPTreeNode[] => [
  {
    key: 'sop-category-design',
    title: '设计流程',
    isFolder: true,
    category: 'design',
    children: [
      {
        key: 'sop-1',
        title: '航道设计流程',
        description: '进港航道设计标准流程',
        category: 'design',
        isFolder: false,
        isLeaf: true
      },
      {
        key: 'sop-2',
        title: '码头选址评估',
        description: '港址选择与评估流程',
        category: 'design',
        isFolder: false,
        isLeaf: true
      }
    ]
  },
  {
    key: 'sop-category-capacity',
    title: '能力测算',
    isFolder: true,
    category: 'capacity',
    children: [
      {
        key: 'sop-3',
        title: '泊位通过能力计算',
        description: '泊位设计通过能力计算流程',
        category: 'capacity',
        isFolder: false,
        isLeaf: true
      }
    ]
  }
]

/**
 * 管理经验库树状态。
 */
export function useSopTree() {
  const treeData = ref<SOPTreeNode[]>([])
  const selectedNode = ref<SOPTreeNode | null>(null)

  /**
   * 设置经验库树数据。
   */
  const setTreeData = (nodes: SOPTreeNode[]) => {
    treeData.value = nodes
  }

  /**
   * 重置为默认经验库树数据。
   */
  const resetToDefaultTree = () => {
    treeData.value = createDefaultSopTree()
  }

  /**
   * 递归查找指定经验库节点。
   */
  const findNode = (nodes: SOPTreeNode[], key: string): SOPTreeNode | null => {
    for (const node of nodes) {
      if (node.key === key) {
        return node
      }

      if (node.children?.length) {
        const found = findNode(node.children, key)
        if (found) {
          return found
        }
      }
    }

    return null
  }

  /**
   * 记录当前选中的经验库节点。
   */
  const setSelectedNode = (node: SOPTreeNode | null) => {
    selectedNode.value = node
  }

  return {
    treeData,
    selectedNode,
    createDefaultSopTree,
    setTreeData,
    resetToDefaultTree,
    findNode,
    setSelectedNode
  }
}
