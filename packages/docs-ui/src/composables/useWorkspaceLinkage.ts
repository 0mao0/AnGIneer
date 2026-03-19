import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { StructuredIndexItem } from '../types/knowledge'

export interface LinkedHighlight {
  id: string
  itemId: string
  structuredItemId?: string
  page: number
  hasRect: boolean
  left: number
  top: number
  width: number
  height: number
  lineStart: number | null
  lineEnd: number | null
  type?: string
}

interface GraphDataLike {
  nodes: any[]
  edges: any[]
}

interface UseWorkspaceLinkageOptions {
  graphData: ComputedRef<GraphDataLike | null | undefined>
  structuredItems: ComputedRef<StructuredIndexItem[]>
  markdownContent: ComputedRef<string>
  isPdf: ComputedRef<boolean>
  pdfPage: Ref<number>
  rightScrollPercent: Ref<number>
}

const readNumeric = (value: unknown): number | null => {
  const numberValue = Number(value)
  if (!Number.isFinite(numberValue)) return null
  return numberValue
}

const readFirstNumeric = (source: Record<string, any>, keys: string[]): number | null => {
  const readByPath = (payload: Record<string, any>, keyPath: string): unknown => {
    if (!keyPath.includes('.')) return payload[keyPath]
    return keyPath.split('.').reduce<unknown>((value, segment) => {
      if (!value || typeof value !== 'object') return undefined
      return (value as Record<string, any>)[segment]
    }, payload)
  }
  for (const key of keys) {
    const value = readNumeric(readByPath(source, key))
    if (value !== null) {
      return value
    }
  }
  return null
}

const extractLineRange = (meta: Record<string, any>) => {
  const start = readFirstNumeric(meta, ['line_start', 'lineStart', 'markdown_line_start', 'md_line_start', 'start_line'])
  const end = readFirstNumeric(meta, ['line_end', 'lineEnd', 'markdown_line_end', 'md_line_end', 'end_line'])
  if (start === null || end === null) {
    return { lineStart: null, lineEnd: null }
  }
  return { lineStart: Math.max(1, Math.round(start)), lineEnd: Math.max(1, Math.round(end)) }
}

const normalizeForMatch = (value: string) => value
  .replace(/[０-９]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/[Ａ-Ｚａ-ｚ]/g, char => String.fromCharCode(char.charCodeAt(0) - 65248))
  .replace(/\s+/g, ' ')
  .replace(/[^\u4e00-\u9fa5a-zA-Z0-9 ]+/g, ' ')
  .trim()
  .toLowerCase()

const scoreHighlightCandidate = (
  item: LinkedHighlight,
  matchedId: string,
  exactItemId: string | null,
  preferredPage: number | null
) => {
  let score = 0
  if (exactItemId && item.itemId === exactItemId) {
    score += 1600
  }
  if (item.structuredItemId === matchedId) {
    score += 1200
  }
  if (item.itemId === matchedId) {
    score += 1000
  }
  if (item.hasRect) {
    score += 360
  }
  if (item.lineStart !== null) {
    score += 40
  }
  if (preferredPage !== null) {
    if (item.page === preferredPage) {
      score += 240
    } else {
      score -= Math.min(180, Math.abs(item.page - preferredPage) * 18)
    }
  }
  const area = item.width * item.height
  if (Number.isFinite(area) && area > 0) {
    score += Math.min(50, area * 12)
  }
  return score
}

const findNearestHighlight = (
  candidateLine: number | null,
  candidatePage: number | null,
  pool: LinkedHighlight[]
) => {
  if (!pool.length) return null
  if (candidateLine === null && candidatePage === null) return pool[0]
  let best: LinkedHighlight | null = null
  let bestScore = Number.POSITIVE_INFINITY
  pool.forEach(item => {
    if (candidatePage !== null && item.page !== candidatePage) return
    const lineForScore = candidateLine === null ? item.lineStart ?? 1 : candidateLine
    const distance = Math.abs((item.lineStart ?? lineForScore) - lineForScore)
    if (distance < bestScore) {
      best = item
      bestScore = distance
    }
  })
  if (best) return best
  if (candidatePage !== null) {
    return pool.find(item => item.page === candidatePage) || null
  }
  return pool[0]
}

export function useWorkspaceLinkage(options: UseWorkspaceLinkageOptions) {
  const activeLinkedItemId = ref<string | null>(null)
  const highlightLinkEnabled = ref(true)
  const middleMarkdownLines = computed(() => options.markdownContent.value.split('\n'))
  const showHighlightToggle = computed(() => (options.graphData.value?.nodes || []).length > 0)

  const findLineRangeFromMiddle = (item: StructuredIndexItem): { lineStart: number; lineEnd: number } | null => {
    const source = [item.content, item.title]
      .find(value => typeof value === 'string' && value.trim().length > 0)
    if (!source) return null
    const normalizedNeedle = normalizeForMatch(source)
    if (!normalizedNeedle) return null
    const needle = normalizedNeedle.slice(0, 80)
    let matchIndex = -1
    for (let index = 0; index < middleMarkdownLines.value.length; index += 1) {
      const line = normalizeForMatch(middleMarkdownLines.value[index] || '')
      if (!line) continue
      if (line.includes(needle) || needle.includes(line.slice(0, Math.min(40, line.length)))) {
        matchIndex = index
        break
      }
    }
    if (matchIndex < 0) return null
    const lineStart = matchIndex + 1
    const lineEnd = Math.min(lineStart + 2, middleMarkdownLines.value.length || lineStart)
    return { lineStart, lineEnd }
  }

  const getItemLineRange = (item: StructuredIndexItem): { lineStart: number; lineEnd: number } | null => {
    const meta = (item.meta || {}) as Record<string, any>
    const fromMeta = extractLineRange(meta)
    if (fromMeta.lineStart !== null && fromMeta.lineEnd !== null) {
      return fromMeta
    }
    const inferredLine = readFirstNumeric(meta, ['line', 'start_line', 'line_start', 'lineStart'])
    if (inferredLine !== null) {
      const line = Math.max(1, Math.round(inferredLine))
      return { lineStart: line, lineEnd: line }
    }
    return findLineRangeFromMiddle(item)
  }

  const linkedHighlights = computed<LinkedHighlight[]>(() => {
    const nodes = options.graphData.value?.nodes || []
    const nodeSeqKeyMap = new Map<string, string>()
    nodes.forEach(node => {
      const nodeId = String(node.id || '').trim()
      if (!nodeId) return
      const page = Number(node.page_idx ?? 0) + 1
      const blockSeq = Number(node.block_seq ?? 0)
      if (page > 0 && blockSeq > 0) {
        nodeSeqKeyMap.set(nodeId, `p${page}b${blockSeq}`)
      }
    })

    const highlightPool = nodes
      .filter(node => {
        const type = node.block_type || 'text'
        if (['header', 'footer', 'page_header', 'page_number'].includes(type)) {
          return false
        }
        return true
      })
      .map((node, index) => {
        const page = (node.page_idx ?? 0) + 1
        const bbox = node.bbox
        const type = node.block_type || 'text'

        let normalizedRect = null
        if (bbox && Array.isArray(bbox) && bbox.length >= 4) {
          const [x0, y0, x1, y1] = bbox
          normalizedRect = {
            left: Math.max(0, Math.min(x0, x1)),
            top: Math.max(0, Math.min(y0, y1)),
            width: Math.abs(x1 - x0),
            height: Math.abs(y1 - y0)
          }
        }

        return {
          id: `highlight-${node.id || index}`,
          itemId: node.id || `node-${index}`,
          page,
          hasRect: Boolean(normalizedRect),
          left: normalizedRect?.left ?? 0,
          top: normalizedRect?.top ?? 0,
          width: normalizedRect?.width ?? 0,
          height: normalizedRect?.height ?? 0,
          lineStart: null,
          lineEnd: null,
          type
        }
      })

    if (!options.structuredItems.value.length) {
      return highlightPool
    }

    const collectStructuredRefs = (item: StructuredIndexItem, fallbackId: string): string[] => {
      const meta = item.meta || {}
      const rawRefs: unknown[] = [
        item.id,
        fallbackId,
        meta.block_uid,
        meta.blockUid,
        meta.mineru_block_uid,
        meta.mineruBlockUid,
        meta.node_id,
        meta.nodeId,
        meta.block_id,
        meta.blockId,
        meta.source_block_id,
        meta.sourceBlockId,
        meta.mineru_block_id,
        meta.mineruBlockId,
        meta.caption_block_uid,
        meta.footnote_block_uid,
        meta.caption_block_uids,
        meta.footnote_block_uids,
        meta.block_uids,
        meta.node_ids
      ]
      const refs: string[] = []
      rawRefs.forEach(value => {
        if (Array.isArray(value)) {
          value.forEach(inner => {
            const text = String(inner || '').trim()
            if (text) refs.push(text)
          })
          return
        }
        const text = String(value || '').trim()
        if (text) refs.push(text)
      })
      return Array.from(new Set(refs))
    }

    const blockToItemMap = new Map<string, string>()
    const seqToItemMap = new Map<string, string>()
    const itemLineRanges = new Map<string, { lineStart: number, lineEnd: number }>()

    options.structuredItems.value.forEach((item, index) => {
      const itemId = item.id || `item-${index}`
      const meta = item.meta || {}
      const refs = collectStructuredRefs(item, itemId)

      refs.forEach(ref => {
        blockToItemMap.set(ref, itemId)
      })

      const pageSeq = Number(meta.page_seq || meta.page || 0)
      const blockSeq = Number(meta.block_seq || 0)
      if (pageSeq > 0 && blockSeq > 0) {
        seqToItemMap.set(`p${pageSeq}b${blockSeq}`, itemId)
      }

      const range = getItemLineRange(item)
      if (range) {
        itemLineRanges.set(itemId, range)
      }
    })

    return highlightPool.map(highlight => {
      const originalId = highlight.itemId
      const seqKey = nodeSeqKeyMap.get(originalId)
      const linkedId = blockToItemMap.get(originalId) || seqToItemMap.get(seqKey || '')

      if (linkedId) {
        const range = itemLineRanges.get(linkedId)
        return {
          ...highlight,
          structuredItemId: linkedId,
          lineStart: range?.lineStart ?? highlight.lineStart,
          lineEnd: range?.lineEnd ?? highlight.lineEnd
        }
      }

      return highlight
    })
  })

  const resolveLinkedHighlight = (
    id: string | null | undefined,
    exactItemId: string | null = null,
    preferredPage: number | null = options.isPdf.value ? options.pdfPage.value : null
  ): LinkedHighlight | null => {
    if (!id) return null
    const candidates = linkedHighlights.value.filter(item =>
      item.itemId === id || item.structuredItemId === id
    )
    if (!candidates.length) return null
    let target = candidates[0]
    let targetScore = scoreHighlightCandidate(target, id, exactItemId, preferredPage)
    for (let index = 1; index < candidates.length; index += 1) {
      const current = candidates[index]
      const score = scoreHighlightCandidate(current, id, exactItemId, preferredPage)
      if (score > targetScore) {
        target = current
        targetScore = score
      }
    }
    return target
  }

  const activeLinkedHighlight = computed(() => {
    if (!activeLinkedItemId.value) return null
    return resolveLinkedHighlight(activeLinkedItemId.value)
  })

  const activeLeftHighlightId = computed(() => activeLinkedHighlight.value?.itemId || activeLinkedItemId.value)

  const activeLinkedLineRange = computed(() => {
    const current = activeLinkedHighlight.value
    if (!current || current.lineStart === null || current.lineEnd === null) return null
    return {
      start: current.lineStart,
      end: current.lineEnd
    }
  })

  const scrollRightByLine = (lineStart: number) => {
    const lineCount = Math.max(1, options.markdownContent.value.split('\n').length)
    const ratio = Math.max(0, Math.min(1, (lineStart - 1) / lineCount))
    options.rightScrollPercent.value = ratio
  }

  const onHoverLinkedItem = (itemId: string | null) => {
    if (!highlightLinkEnabled.value) return
    if (!itemId) {
      activeLinkedItemId.value = null
      return
    }
    const target = resolveLinkedHighlight(itemId, itemId)
    activeLinkedItemId.value = target?.itemId || itemId
  }

  const onSelectHighlightFromLeft = (itemId: string) => {
    if (!highlightLinkEnabled.value) return
    const target = resolveLinkedHighlight(itemId, itemId, options.isPdf.value ? options.pdfPage.value : null)
    activeLinkedItemId.value = target?.itemId || itemId
    if (!target) return
    if (target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const onSelectItemFromRight = (itemId: string) => {
    if (!highlightLinkEnabled.value) return
    const target = resolveLinkedHighlight(itemId, itemId, null)
    activeLinkedItemId.value = target?.structuredItemId || target?.itemId || itemId
    if (!target) return
    if (target.lineStart !== null && target.lineEnd !== null) {
      scrollRightByLine(target.lineStart)
    }
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const onSelectLineFromRight = (line: number) => {
    if (!highlightLinkEnabled.value) return
    const target = findNearestHighlight(
      Math.max(1, Math.round(line)),
      options.isPdf.value ? options.pdfPage.value : null,
      linkedHighlights.value
    )
    if (!target) return
    activeLinkedItemId.value = target.structuredItemId || target.itemId
    if (options.isPdf.value && target.page !== options.pdfPage.value) {
      options.pdfPage.value = target.page
    }
  }

  const toggleHighlightLink = () => {
    highlightLinkEnabled.value = !highlightLinkEnabled.value
    if (!highlightLinkEnabled.value) {
      activeLinkedItemId.value = null
    }
  }

  const resetLinkageState = () => {
    activeLinkedItemId.value = null
  }

  watch([linkedHighlights, options.pdfPage, highlightLinkEnabled], () => {
    if (!highlightLinkEnabled.value) return
    const currentPageHighlights = linkedHighlights.value
      .filter(item => item.page === options.pdfPage.value)
      .filter(item => item.hasRect)
    if (!currentPageHighlights.length) {
      if (activeLinkedItemId.value && !linkedHighlights.value.some(item =>
        item.itemId === activeLinkedItemId.value || item.structuredItemId === activeLinkedItemId.value
      )) {
        activeLinkedItemId.value = null
      }
      return
    }
    const hasActiveOnPage = currentPageHighlights.some(item =>
      item.itemId === activeLeftHighlightId.value || item.structuredItemId === activeLinkedItemId.value
    )
    if (!hasActiveOnPage) {
      activeLinkedItemId.value = currentPageHighlights[0].structuredItemId || currentPageHighlights[0].itemId
    }
  }, { immediate: true })

  return {
    linkedHighlights,
    activeLinkedItemId,
    highlightLinkEnabled,
    showHighlightToggle,
    activeLeftHighlightId,
    activeLinkedLineRange,
    onHoverLinkedItem,
    onSelectHighlightFromLeft,
    onSelectItemFromRight,
    onSelectLineFromRight,
    toggleHighlightLink,
    resetLinkageState
  }
}
