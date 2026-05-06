import { ref, nextTick } from 'vue'
import { message } from 'ant-design-vue'
import { knowledgeApi } from '@/api/knowledge'
import type {
  StructuredIndexItem,
  StructuredStats,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  KnowledgeStrategy
} from '@angineer/docs-ui'

/** 从行文本中提取页码提示 */
const extractPageHintFromLine = (line: string): number | null => {
  const match = line.match(/[（(]\s*(\d{1,4})\s*[）)]\s*$/)
  if (!match) return null
  const page = Number(match[1])
  if (!Number.isFinite(page) || page <= 0) return null
  return Math.round(page)
}

/** 管理结构化索引：加载、CRUD、批量操作、undo */
export function useKnowledgeStructuredIndex() {
  const structuredStats = ref<StructuredStats>({})
  const structuredItems = ref<StructuredIndexItem[]>([])

  /** 当无结构化索引时，从文档内容中提取标题行作为回退索引 */
  const buildMiddleFallbackItems = (content: string): StructuredIndexItem[] => {
    if (!content.trim()) return []
    const lines = content.split('\n')
    const result: StructuredIndexItem[] = []
    let orderIndex = 0
    lines.forEach((line: string, index: number) => {
      const trimmed = (line || '').trim()
      if (!trimmed) return
      const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/)
      const numberedMatch = trimmed.match(/^(\d+(?:\.\d+)*)(?:[、.)])?\s*(.*)$/)
      if (!headingMatch && !numberedMatch) return
      const numberedPrefix = numberedMatch?.[1] || ''
      const numberedText = (numberedMatch?.[2] || '').trim()
      const text = (
        headingMatch?.[2]
        || (numberedPrefix && numberedText ? `${numberedPrefix} ${numberedText}` : numberedPrefix)
        || numberedText
        || ''
      ).trim().slice(0, 200)
      if (!text) return
      const pageHint = extractPageHintFromLine(trimmed)
      result.push({
        id: `middle-${index + 1}`,
        item_type: headingMatch ? 'heading' : 'section',
        title: text,
        content: text,
        order_index: orderIndex++,
        meta: {
          line_start: index + 1,
          line_end: index + 1,
          heading_level: headingMatch ? headingMatch[1].length : undefined,
          page: pageHint ?? undefined,
          page_no: pageHint ?? undefined
        }
      })
    })
    return result
  }

  /** 加载结构化索引统计 */
  const loadStructuredStats = async (docId: string) => {
    try {
      const result = await knowledgeApi.getStructuredStats(docId) as any
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
      const result = await knowledgeApi.getStructuredIndex(selectedNode.key, strategy, itemType, keyword)
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
      await knowledgeApi.updateDocumentBlock('default', selectedNode.key, payload)
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
      const result = await knowledgeApi.batchOperateDocumentBlocks('default', selectedNode.key, payload)
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
      const result = await knowledgeApi.undoLastDocumentBlockOperation('default', selectedNode.key)
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
