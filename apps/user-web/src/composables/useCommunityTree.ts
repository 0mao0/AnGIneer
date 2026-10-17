/** 公开两页左树数据源：GET /tree 平铺 nodes+items → SmartTreeNode[]（带业务位），含选中态。
 *  排序复用 SmartTree 共用工具 sortTreeNodes（foldersFirst + numberedFirst）：
 *  目录按 sort_order，条目按标题编号前缀（1【金融】…）升序、无编号按拼音兜底。 */
import { computed, ref } from 'vue'
import { buildTreeFromFlat, type SmartTreeNode } from '@angineer/smartree'
import { communityApi, type CommunityScope, type TreeItem, type TreeNode } from '@/api/community'

/** 业务位随索引签名上浮（SmartTreeNode 契约），PublicTreePanel 的 title slot 直读 */
export interface CommunityTreeNode extends SmartTreeNode {
  // isFolder/parentId 沿用 SmartTreeNode 基类型（收窄会让本型不可赋值回 SmartTreeNode[]，
  // 与 SmartTree 组件 props/emit 的契约打架）；count 为目录内条目总数（含子目录）
  communityItem?: TreeItem
  communityNodeId?: string
  sort_order?: number
  communityCount?: number
  // 基接口 children 是 SmartTreeNode[]，这里收窄为本型——否则递归处类型对不上
  children?: CommunityTreeNode[]
}

export function useCommunityTree(scope: CommunityScope) {
  const nodes = ref<TreeNode[]>([])
  const items = ref<TreeItem[]>([])
  const loading = ref(false)
  const loadError = ref('')
  const selectedKey = ref('')
  const selectedItem = ref<TreeItem | null>(null)
  // 给树的选中高亮通道（SmartTree defaultSelectedKeys）：进页自动选中首个条目时同步树内高亮
  const selectedKeys = computed(() => (selectedKey.value ? [selectedKey.value] : []))

  const treeData = computed<CommunityTreeNode[]>(() => {
    const folderRows: CommunityTreeNode[] = nodes.value.map((n) => ({
      key: `n:${n.node_id}`,
      title: n.title,
      isFolder: true,
      selectable: false,
      communityNodeId: n.node_id,
      parentId: n.parent_id ?? undefined,
      sort_order: n.sort_order,
    }))
    const itemRows: CommunityTreeNode[] = items.value.map((item) => ({
      key: `i:${item.item_id}`,
      title: item.title,
      isFolder: false,
      isLeaf: true,
      communityItem: item,
      // 挂不上节点（人工绑过但目录被删）→ buildTreeFromFlat 按孤儿兜底挂根，别让用户看不见
      parentId: item.node_id || undefined,
    }))
    // 装配 + 逐层排序一律用 SmartTree 共用工具（foldersFirst + numberedFirst）。
    // 旧实现自写组装只把「条目」挂进目录、**从不挂子文件夹**——SOP 树出二层分类时整层被丢掉
    // （10-15 实踩：水运下四个子类在 DOM 里一个都没有）；共用工具天然递归挂载，别再自写。
    // parentId 存的是裸 node_id，目录行 key 是 `n:<node_id>`——挂载键要归一到同一命名空间
    const built = buildTreeFromFlat<CommunityTreeNode>({
      folders: folderRows,
      items: itemRows,
      getParentKey: (n) => (n.parentId ? `n:${n.parentId}` : null),
      foldersFirst: true,
      numberedFirst: true,
    })
    // 目录计数（含子目录，展示用，不落库）
    const countItems = (rows: CommunityTreeNode[]): number =>
      rows.reduce((acc, r) => acc + (r.communityItem ? 1 : 0) + countItems(r.children || []), 0)
    const fillCounts = (rows: CommunityTreeNode[]) => {
      rows.forEach((r) => {
        if (r.children?.length) {
          r.communityCount = countItems(r.children)
          fillCounts(r.children)
        }
      })
    }
    fillCounts(built)
    return built
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

  return { nodes, items, loading, loadError, treeData, selectedKey, selectedKeys, selectedItem, reload, select }
}
