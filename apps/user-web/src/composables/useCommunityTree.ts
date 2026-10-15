/** 公开两页左树数据源：GET /tree 平铺 nodes+items → SmartTreeNode[]（带业务位），含选中态。
 *  排序复用 SmartTree 共用工具 sortTreeNodes（foldersFirst + numberedFirst）：
 *  目录按 sort_order，条目按标题编号前缀（1【金融】…）升序、无编号按拼音兜底。 */
import { computed, ref } from 'vue'
import { sortTreeNodes, type SmartTreeNode } from '@angineer/smartree'
import { communityApi, type CommunityScope, type TreeItem, type TreeNode } from '@/api/community'

/** 业务位随索引签名上浮（SmartTreeNode 契约），PublicTreePanel 的 title slot 直读 */
export interface CommunityTreeNode extends SmartTreeNode {
  isFolder: boolean
  communityItem?: TreeItem
  communityNodeId?: string
  // sortTreeNodes 读 sort_order（目录排序键）；count 为目录内条目总数（含子目录）
  sort_order?: number
  communityCount?: number
  // 基接口 children 是 SmartTreeNode[]，这里收窄为本型——否则 sortTreeNodes 递归处类型对不上
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
        sort_order: n.sort_order,
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
    // 计数与排序自底向上：先排子层、回写 children，再排本层（SmartTree 共用规则）
    const countItems = (rows: CommunityTreeNode[]): number =>
      rows.reduce((acc, r) => acc + (r.communityItem ? 1 : 0) + countItems(r.children || []), 0)
    const sortLevel = (rows: CommunityTreeNode[]): CommunityTreeNode[] => {
      rows.forEach((r) => {
        if (r.children?.length) {
          r.children = sortLevel(r.children)
          r.communityCount = countItems(r.children)
        }
      })
      return sortTreeNodes(rows, { foldersFirst: true, numberedFirst: true })
    }
    return sortLevel(byParent.get(null) || [])
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
