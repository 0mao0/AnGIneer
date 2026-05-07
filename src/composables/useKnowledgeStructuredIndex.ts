import { ref, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import type {
  KnowledgeStructuredApi,
  StructuredIndexItem,
  StructuredStats,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  KnowledgeStrategy
} from '../types'
import { buildMiddleFallbackItems } from '../utils/knowledge'

/** 管理结构化索引：加载、CRUD、批量操作、undo */
export function useKnowledgeStructuredIndex(api: KnowledgeStructuredApi) {
  const structuredStats = ref<StructuredStats>({})
  const structuredItems = ref<StructuredIndexItem[]>([])

  /** 加载结构化索引统计 */
  const loadStructuredStats = async (docId: string) => {
    try {
      const result = await api.getStructuredStats(docId) as any
      structuredStats.value = result || {}
    } catch {
      structuredStats.value = {}
    }
  }

  /** 加载结构化索引条目 */
  const loadStructuredIndex = async (
    selectedNode: any,
    docContent: string,
    itemType?: string,
    keyword?: string
  ) => {
    if (!selectedNode || selectedNode.isFolder) {
      structuredItems.value = []
      return
    }
    const strategy = selectedNode.strategy as KnowledgeStrategy | undefined
    if (!strategy) {
      structuredItems.value = []
      return
    }
    try {
      const result = await api.getStructuredIndex(selectedNode.key, strategy, itemType, keyword)
      const fromApi = Array.isArray(result?.items) ? result.items : []
      structuredItems.value = fromApi.length ? fromApi : buildMiddleFallbackItems(docContent)
    } catch {
      structuredItems.value = buildMiddleFallbackItems(docContent)
    }
  }

  /** 更新单个结构节点 */
  const updateStructuredNode = async (
    payload: StructuredNodeUpdatePayload,
    selectedNode: any,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>
  ) => {
    if (!selectedNode || selectedNode.isFolder) return
    try {
      await api.updateDocumentBlock('default', selectedNode.key, payload)
      await onLoadDocContent(selectedNode.key)
      await onLoadStructuredStats(selectedNode.key)
      await onLoadStructuredIndex()
      message.success('节点内容已更新')
    } catch (error) {
      const detail = (error as any)?.response?.data?.detail || (error as any)?.message
      message.error(detail ? `节点更新失败: ${detail}` : '节点更新失败')
      throw error
    }
  }

  /** 批量操作结构节点 */
  const batchOperateStructuredNodes = async (
    payload: StructuredBatchOperationPayload,
    selectedNode: any,
    workspaceRef: any,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>
  ) => {
    if (!selectedNode || selectedNode.isFolder) return
    try {
      const result = await api.batchOperateDocumentBlocks('default', selectedNode.key, payload) as any
      await onLoadDocContent(selectedNode.key)
      await onLoadStructuredStats(selectedNode.key)
      await onLoadStructuredIndex()
      if (payload.operation === 'merge') {
        const targetBlockId = String(result.target_block_id || payload.targetBlockId || '').trim()
        if (targetBlockId) {
          await nextTick()
          workspaceRef?.setActiveLinkedItem(targetBlockId)
        }
      }
      if (payload.operation === 'split') {
        const focusBlockId = String(result.created_block_ids?.[0] || payload.blockIds?.[0] || '').trim()
        if (focusBlockId) {
          await nextTick()
          workspaceRef?.setActiveLinkedItem(focusBlockId)
        }
      }
      if (payload.operation === 'relevel') {
        const focusBlockId = String(result.updated_block_ids?.[0] || payload.blockIds?.[0] || '').trim()
        if (focusBlockId) {
          await nextTick()
          workspaceRef?.setActiveLinkedItem(focusBlockId)
        }
      }
      const successText = payload.operation === 'merge'
        ? '批量合并已完成'
        : payload.operation === 'relevel'
          ? (
              typeof payload.targetLevel === 'number'
                ? `已将 ${result.updated_block_ids?.length || payload.blockIds.length || 0} 个节点设为 L${payload.targetLevel}`
                : `已调整 ${result.updated_block_ids?.length || payload.blockIds.length || 0} 个标题层级`
            )
          : payload.operation === 'delete'
            ? `已删除 ${result.removed_block_ids?.length || payload.blockIds.length || 0} 个 block`
            : `Block 已拆分为 ${Math.max(2, (result.created_block_ids?.length || 0) + 1)} 段`
      message.success(successText)
    } catch (error) {
      const detail = (error as any)?.response?.data?.detail || (error as any)?.message
      message.error(detail ? `结构操作失败: ${detail}` : '结构操作失败')
      throw error
    }
  }

  /** 撤回最近一次结构操作 */
  const undoLastStructuredOperation = async (
    selectedNode: any,
    workspaceRef: any,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>
  ) => {
    if (!selectedNode || selectedNode.isFolder) return
    try {
      const result = await api.undoLastDocumentBlockOperation('default', selectedNode.key) as any
      await onLoadDocContent(selectedNode.key)
      await onLoadStructuredStats(selectedNode.key)
      await onLoadStructuredIndex()
      const firstRestoredId = String(result.restored_block_ids?.[0] || '').trim()
      if (firstRestoredId) {
        await nextTick()
        workspaceRef?.setActiveLinkedItem(firstRestoredId)
      }
      message.success('最近一次结构操作已撤回')
    } catch (error) {
      const detail = (error as any)?.response?.data?.detail || (error as any)?.message
      message.error(detail ? `撤回结构操作失败: ${detail}` : '撤回结构操作失败')
      throw error
    }
  }

  return {
    structuredStats,
    structuredItems,
    buildMiddleFallbackItems,
    loadStructuredStats,
    loadStructuredIndex,
    updateStructuredNode,
    batchOperateStructuredNodes,
    undoLastStructuredOperation
  }
}
