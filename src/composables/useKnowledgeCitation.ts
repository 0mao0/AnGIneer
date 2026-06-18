import type { CitationReference } from '@angineer/ui-kit'
import { nextTick, type Ref } from 'vue'

type CitationRichMedia = {
  table_html?: string
  math_content?: string
  image_path?: string
  image_paths?: string[]
  rich_media_order?: Array<{ type: 'image' | 'table' | 'math'; path?: string }>
  source_file_name?: string
}

export type KnowledgeChatCitation = {
  label?: string
  target_id?: string
  target_type?: string
  doc_id?: string
  doc_title?: string
  page_idx?: number
  section_path?: string
  snippet?: string
  content?: string
  content_type?: string
  score: number
  reference?: Partial<CitationReference> | null
  rich_media?: CitationRichMedia
}

export type KnowledgeAnswerMessage = {
  role?: string
  content?: string
  queryChain?: string
  citations?: KnowledgeChatCitation[]
  strategy?: string
  task_type?: string
  confidence?: number
  retrieved_items?: Array<{
    item_id: string
    entity_type: string
    text: string
    score: number
    metadata?: Record<string, any>
  }>
  debug?: Record<string, any>
}

/** 归一化引用文本，便于做层级与片段匹配 */
const normalizeCitationText = (value: string): string => String(value || '')
  .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/[Ａ-Ｚａ-ｚ]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/\s+/g, ' ')
  .replace(/[^\u4e00-\u9fa5a-zA-Z0-9 ]+/g, ' ')
  .trim()
  .toLowerCase()

/** 获取层级路径的最后一级标题 */
const getCitationLastSegment = (value: string): string => {
  const segments = String(value || '')
    .split(/\s*\/\s*|\s*>\s*/g)
    .map(item => item.trim())
    .filter(Boolean)
  return segments[segments.length - 1] || String(value || '').trim()
}

/** 统一解析引用目标 ID，优先兼容新的 reference 协议。 */
const getCitationTargetId = (citation: KnowledgeChatCitation | null | undefined): string => String(
  citation?.reference?.targetId || citation?.target_id || ''
).trim()

/** 统一解析引用所在文档 ID，优先兼容新的 reference 协议。 */
const getCitationDocId = (citation: KnowledgeChatCitation | null | undefined): string => String(
  citation?.reference?.docId || citation?.doc_id || ''
).trim()

/** 统一解析引用层级路径，优先兼容新的 reference 协议。 */
const getCitationSectionPath = (citation: KnowledgeChatCitation | null | undefined): string => String(
  citation?.reference?.sectionPath || citation?.section_path || ''
).trim()

/** 统一解析引用片段文本，优先读取 reference 中更完整的正文信息。 */
const getCitationSnippet = (citation: KnowledgeChatCitation | null | undefined): string => String(
  citation?.reference?.content
  || citation?.reference?.snippet
  || citation?.content
  || citation?.snippet
  || ''
).trim()

/** 统一解析引用页码，兼容 reference.pageIdx 与旧 page_idx。 */
const getCitationPage = (citation: KnowledgeChatCitation | null | undefined): number => {
  const referencePage = Number(citation?.reference?.pageIdx || 0)
  if (referencePage > 0) return referencePage
  const legacyPage = Number(citation?.page_idx || 0)
  return legacyPage > 0 ? legacyPage : 0
}

/** 管理引用定位：解析引用目标节点、聚焦文档到对应块 */
export function useKnowledgeCitation() {
  /** 基于 target_id、页码、层级和片段内容，为引用挑选最可能的文档节点 */
  const resolveCitationTargetNode = (
    citation: KnowledgeChatCitation | null | undefined,
    graphNodes: any[]
  ) => {
    if (!graphNodes.length || !citation) return null
    const targetId = getCitationTargetId(citation)
    const normalizedLastSegment = normalizeCitationText(getCitationLastSegment(getCitationSectionPath(citation)))
    const normalizedSnippet = normalizeCitationText(getCitationSnippet(citation))
    let bestNode: any = null
    let bestScore = Number.NEGATIVE_INFINITY
    graphNodes.forEach((node) => {
      let score = 0
      const nodeId = String(node?.id || '').trim()
      const blockUid = String(node?.block_uid || '').trim()
      if (targetId && (nodeId === targetId || blockUid === targetId)) {
        score += 5000
      }
      const nodePage = Number(node?.page_idx ?? -1) + 1
      const citationPage = getCitationPage(citation)
      if (citationPage > 0) {
        if (nodePage === citationPage) {
          score += 320
        } else if (nodePage === citationPage + 1 || nodePage === citationPage - 1) {
          score += 120
        }
      }
      const nodeLastSegment = normalizeCitationText(getCitationLastSegment(String(node?.title_path || node?.title || '')))
      if (normalizedLastSegment && nodeLastSegment) {
        if (nodeLastSegment === normalizedLastSegment) {
          score += 520
        } else if (
          nodeLastSegment.includes(normalizedLastSegment)
          || normalizedLastSegment.includes(nodeLastSegment)
        ) {
          score += 240
        }
      }
      const nodeText = normalizeCitationText([
        node?.plain_text,
        node?.title,
        node?.caption,
        node?.footnote
      ].filter(Boolean).join(' '))
      if (normalizedSnippet && nodeText) {
        const shortNodeText = nodeText.slice(0, 48)
        if (shortNodeText && normalizedSnippet.includes(shortNodeText)) {
          score += 160
        } else if (nodeText.length >= 12 && (nodeText.includes(normalizedSnippet) || normalizedSnippet.includes(nodeText.slice(0, 24)))) {
          score += 100
        }
      }
      if (score > bestScore) {
        bestNode = node
        bestScore = score
      }
    })
    return bestScore > 0 ? bestNode : null
  }

  /** 根据回答引用切换文档并把解析区定位到对应块 */
  const focusCitationInWorkspace = async (
    citation: KnowledgeChatCitation | null | undefined,
    selectedNode: Ref<any>,
    graphData: Ref<any>,
    onLoadNodes: (key?: string) => Promise<void>,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>,
    workspaceRef: any,
    keepCurrentPreview: (docId: string) => boolean
  ) => {
    const targetId = getCitationTargetId(citation)
    const docId = getCitationDocId(citation)
    if (!targetId) return
    if (docId && (!selectedNode.value || selectedNode.value.key !== docId)) {
      await onLoadNodes(docId)
    } else if (docId && !keepCurrentPreview(docId)) {
      await onLoadDocContent(docId)
      await onLoadStructuredStats(docId)
    }
    if (selectedNode.value?.strategy) {
      await onLoadStructuredIndex()
    }
    const resolvedNode = resolveCitationTargetNode(citation, graphData.value?.nodes || [])
    const resolvedTargetId = String(resolvedNode?.id || targetId).trim()
    const resolvedPreferredPage = Number(resolvedNode?.page_idx ?? -1) >= 0
      ? Number(resolvedNode.page_idx) + 1
      : (getCitationPage(citation) > 0 ? getCitationPage(citation) : null)
    await nextTick()
    workspaceRef?.setActiveLinkedItem(resolvedTargetId, {
      preferredPage: resolvedPreferredPage,
      preferLastHighlight: true
    })
  }

  /** 回答完成后自动聚焦到最后一条引用 */
  const handleKnowledgeAnswerComplete = async (
    message: KnowledgeAnswerMessage,
    selectedNode: Ref<any>,
    graphData: Ref<any>,
    onLoadNodes: (key?: string) => Promise<void>,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>,
    workspaceRef: any,
    keepCurrentPreview: (docId: string) => boolean
  ) => {
    const citations = Array.isArray(message?.citations) ? message.citations : []
    const targetCitation = citations[citations.length - 1]
    if (!targetCitation) return
    await focusCitationInWorkspace(
      targetCitation, selectedNode, graphData,
      onLoadNodes, onLoadDocContent, onLoadStructuredStats, onLoadStructuredIndex,
      workspaceRef, keepCurrentPreview
    )
  }

  /** 手动点击参考依据时重新触发文档定位 */
  const handleKnowledgeCitationSelect = async (
    citation: KnowledgeChatCitation,
    selectedNode: Ref<any>,
    graphData: Ref<any>,
    onLoadNodes: (key?: string) => Promise<void>,
    onLoadDocContent: (docId: string) => Promise<void>,
    onLoadStructuredStats: (docId: string) => Promise<void>,
    onLoadStructuredIndex: () => Promise<void>,
    workspaceRef: any,
    keepCurrentPreview: (docId: string) => boolean
  ) => {
    await focusCitationInWorkspace(
      citation, selectedNode, graphData,
      onLoadNodes, onLoadDocContent, onLoadStructuredStats, onLoadStructuredIndex,
      workspaceRef, keepCurrentPreview
    )
  }

  return {
    resolveCitationTargetNode,
    focusCitationInWorkspace,
    handleKnowledgeAnswerComplete,
    handleKnowledgeCitationSelect
  }
}
