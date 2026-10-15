/** 公开两页左树数据源：GET /tree 平铺 nodes+items → SmartTreeNode[]（带业务位），含选中态。 */
import { computed, ref } from 'vue'
import type { SmartTreeNode } from '@angineer/smartree'
import { communityApi, type CommunityScope, type TreeItem, type TreeNode } from '@/api/community'

/** 业务位随索引签名上浮（SmartTreeNode 契约），PublicTreePanel 的 title slot 直读 */
export interface CommunityTreeNode extends SmartTreeNode {
  isFolder: boolean
  communityItem?: TreeItem
  communityNodeId?: string
  // 基接口 children 是 SmartTreeNode[]，这里收窄为本型——否则 sortRows 递归处类型对不上
  children?: CommunityTreeNode[]
}

export function useCommunityTree(scope: CommunityScope) {
  const nodes = ref<TreeNode[]>([])
  const items = ref<TreeItem[]>([])
  const loading = ref(false)
  const loadError = ref('')
  const selectedKey = ref('')
  const selectedItem = ref<TreeItem | null>(null)

  const treeData = computed<CommunityTreeNode[]>(() => {
    const byParent = new Map<string | null, CommunityTreeNode[]>()
    const rowByNode: Record<string, CommunityTreeNode> = {}
    for (const n of nodes.value) {
      const row: CommunityTreeNode = {
        key: `n:${n.node_id}`,
        title: n.title,
        isFolder: true,
        selectable: false,
        communityNodeId: n.node_id,
        children: [],
      }
      rowByNode[n.node_id] = row
      const bucket = byParent.get(n.parent_id) || []
      bucket.push(row)
      byParent.set(n.parent_id, bucket)
    }
    const itemRow = (item: TreeItem): CommunityTreeNode => ({
      key: `i:${item.item_id}`,
      title: item.title,
      isFolder: false,
      isLeaf: true,
      communityItem: item,
    })
    for (const item of items.value) {
      // 挂不上节点（人工绑过但目录被删）→ 挂根上，别让用户看不见
      const parent = rowByNode[item.node_id]
      if (parent) {
        parent.children!.push(itemRow(item))
      } else {
        const roots = byParent.get(null) || []
        roots.push(itemRow(item))
        byParent.set(null, roots)
      }
    }
    const sortRows = (rows: CommunityTreeNode[], order: Record<string, number>): CommunityTreeNode[] => {
      rows.sort((a, b) => {
        if (a.isFolder !== b.isFolder) return a.isFolder ? -1 : 1
        if (a.isFolder) return (order[a.communityNodeId!] ?? 0) - (order[b.communityNodeId!] ?? 0)
        return (a.communityItem?.created_at || '') < (b.communityItem?.created_at || '') ? -1 : 1
      })
      rows.forEach((r) => r.children && sortRows(r.children, order))
      return rows
    }
    const order: Record<string, number> = {}
    nodes.value.forEach((n) => { order[n.node_id] = n.sort_order })
    return sortRows(byParent.get(null) || [], order)
  })

  const selectedFirstLeaf = computed(() => {
    // 进页默认选中第一个可点条目（避免右栏空白）
    const stack = [...treeData.value]
    while (stack.length) {
      const row = stack.shift()!
      if (row.communityItem) return row
      stack.unshift(...(row.children || []))
    }
    return null
  })

  async function reload(keepSelection = true) {
    loading.value = true
    loadError.value = ''
    try {
      const payload = await communityApi.getTree(scope)
      nodes.value = payload.nodes || []
      items.value = payload.items || []
      if (!keepSelection || !selectedKey.value) {
        select(selectedFirstLeaf.value)
      }
    } catch (e: any) {
      loadError.value = e?.response?.data?.detail || '分类目录加载失败'
    } finally {
      loading.value = false
    }
  }

  function select(row: CommunityTreeNode | null) {
    selectedKey.value = row?.key || ''
    selectedItem.value = row?.communityItem || null
  }

  return { nodes, items, loading, loadError, treeData, selectedKey, selectedItem, reload, select }
}
