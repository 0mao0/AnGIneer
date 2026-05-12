import type {
  CitationBinding,
  CitationReference,
  CitationRichMediaValue,
  InlineCitationCandidate,
  InlineCitationDraftValue,
  InlineCitationSearchPayload
} from '../types/citation'
import type { BaseChatCitation } from '../types/chat'

const randomPart = () => Math.random().toString(36).slice(2, 8)

export const createCitationId = () => `cit_${Date.now().toString(36)}_${randomPart()}`

export const formatCitationDocTitle = (title?: string | null): string => {
  const normalized = String(title || '').trim()
  if (!normalized) return ''
  if (
    (normalized.startsWith('《') && normalized.endsWith('》'))
    || (normalized.startsWith('<') && normalized.endsWith('>'))
  ) {
    return normalized
  }
  return `《${normalized}》`
}

export const normalizeCitationRichMedia = (
  richMedia?: Partial<CitationRichMediaValue> | null
): CitationRichMediaValue | undefined => {
  if (!richMedia) return undefined
  const normalized: CitationRichMediaValue = {
    tableHtml: String(richMedia.tableHtml || '').trim() || undefined,
    mathContent: String(richMedia.mathContent || '').trim() || undefined,
    imagePath: String(richMedia.imagePath || '').trim() || undefined,
    imagePaths: Array.isArray(richMedia.imagePaths)
      ? richMedia.imagePaths.map(item => String(item || '').trim()).filter(Boolean)
      : undefined,
    richMediaOrder: Array.isArray(richMedia.richMediaOrder)
      ? richMedia.richMediaOrder
        .filter(Boolean)
        .map(item => ({ type: item.type, ...(item.path ? { path: String(item.path) } : {}) }))
      : undefined,
    sourceFileName: String(richMedia.sourceFileName || '').trim() || undefined
  }
  return Object.values(normalized).some(Boolean) ? normalized : undefined
}

export const normalizeInlineCitationDraft = (
  value?: Partial<InlineCitationDraftValue> | null
): InlineCitationDraftValue => ({
  content: String(value?.content || ''),
  citations: Array.isArray(value?.citations)
    ? value!.citations
      .filter(Boolean)
      .map(citation => ({
        ...citation,
        id: citation.id || createCitationId(),
        label: String(citation.label || ''),
        triggerText: String(citation.triggerText || ''),
        range: {
          start: Math.max(0, Number(citation.range?.start || 0)),
          end: Math.max(0, Number(citation.range?.end || 0))
        },
        reference: {
          ...citation.reference,
          targetId: String(citation.reference?.targetId || ''),
          targetType: String(citation.reference?.targetType || 'content'),
          docId: String(citation.reference?.docId || ''),
          docTitle: String(citation.reference?.docTitle || ''),
          pageIdx: Number(citation.reference?.pageIdx || 0) || undefined,
          sectionPath: String(citation.reference?.sectionPath || '') || undefined,
          snippet: String(citation.reference?.snippet || '') || undefined,
          content: String(citation.reference?.content || '') || undefined,
          contentType: String(citation.reference?.contentType || '') || undefined,
          score: Number(citation.reference?.score || 0) || undefined,
          sourceVersion: String(citation.reference?.sourceVersion || '') || undefined,
          libraryId: String(citation.reference?.libraryId || '') || undefined,
          richMedia: normalizeCitationRichMedia(citation.reference?.richMedia)
        }
      }))
      .sort((left, right) => left.range.start - right.range.start)
    : []
})

export const buildCitationSegments = (value: InlineCitationDraftValue): Array<
  { type: 'text'; text: string; key: string }
  | { type: 'citation'; binding: CitationBinding; key: string }
> => {
  const normalized = normalizeInlineCitationDraft(value)
  const segments: Array<
    { type: 'text'; text: string; key: string }
    | { type: 'citation'; binding: CitationBinding; key: string }
  > = []
  let cursor = 0
  normalized.citations.forEach((binding) => {
    const start = Math.max(0, Math.min(binding.range.start, normalized.content.length))
    const end = Math.max(start, Math.min(binding.range.end, normalized.content.length))
    if (start > cursor) {
      segments.push({
        type: 'text',
        text: normalized.content.slice(cursor, start),
        key: `text_${cursor}_${start}`
      })
    }
    segments.push({
      type: 'citation',
      binding: {
        ...binding,
        range: { start, end }
      },
      key: binding.id
    })
    cursor = end
  })
  if (cursor < normalized.content.length || !segments.length) {
    segments.push({
      type: 'text',
      text: normalized.content.slice(cursor),
      key: `text_${cursor}_${normalized.content.length}`
    })
  }
  return segments
}

export const shiftCitationRanges = (
  citations: CitationBinding[],
  fromOffset: number,
  delta: number
): CitationBinding[] => citations.map((citation) => {
  if (citation.range.end <= fromOffset) {
    return citation
  }
  return {
    ...citation,
    range: {
      start: citation.range.start + delta,
      end: citation.range.end + delta
    }
  }
})

export const insertCitationBinding = (
  value: InlineCitationDraftValue,
  selection: { start: number; end: number },
  candidate: InlineCitationCandidate
): InlineCitationDraftValue => {
  const normalized = normalizeInlineCitationDraft(value)
  const start = Math.max(0, Math.min(selection.start, normalized.content.length))
  const end = Math.max(start, Math.min(selection.end, normalized.content.length))
  const label = String(candidate.label || '').trim()
  const nextContent = `${normalized.content.slice(0, start)}${label}${normalized.content.slice(end)}`
  const delta = label.length - (end - start)
  const preserved = normalized.citations
    .filter(citation => citation.range.end <= start || citation.range.start >= end)
    .map(citation => (
      citation.range.start >= end
        ? {
          ...citation,
          range: {
            start: citation.range.start + delta,
            end: citation.range.end + delta
          }
        }
        : citation
    ))
  const insertedBinding: CitationBinding = {
    id: createCitationId(),
    label,
    triggerText: String(candidate.triggerText || label),
    range: {
      start,
      end: start + label.length
    },
    reference: candidate.reference,
    status: 'active'
  }
  return {
    content: nextContent,
    citations: [...preserved, insertedBinding].sort((left, right) => left.range.start - right.range.start)
  }
}

export const findMentionAtCaret = (
  content: string,
  caretOffset: number
): { query: string; start: number; end: number } | null => {
  const safeOffset = Math.max(0, Math.min(caretOffset, content.length))
  const prefix = content.slice(0, safeOffset)
  const match = prefix.match(/@([^\s@]{0,64})$/)
  if (!match) return null
  const query = String(match[1] || '')
  const start = prefix.length - query.length - 1
  return { query, start, end: safeOffset }
}

export const mapReferenceToBaseChatCitation = (reference: CitationReference): BaseChatCitation => ({
  target_id: reference.targetId,
  target_type: reference.targetType,
  doc_id: reference.docId,
  doc_title: reference.docTitle,
  page_idx: Number(reference.pageIdx || 0),
  section_path: String(reference.sectionPath || ''),
  snippet: String(reference.snippet || ''),
  content: String(reference.content || ''),
  content_type: String(reference.contentType || ''),
  score: Number(reference.score || 0),
  rich_media: reference.richMedia
    ? {
      table_html: reference.richMedia.tableHtml,
      math_content: reference.richMedia.mathContent,
      image_path: reference.richMedia.imagePath,
      image_paths: reference.richMedia.imagePaths,
      rich_media_order: reference.richMedia.richMediaOrder,
      source_file_name: reference.richMedia.sourceFileName
    }
    : undefined
})

export const mapBaseChatCitationToReference = (
  citation: BaseChatCitation,
  libraryId?: string
): CitationReference => ({
  targetId: citation.target_id,
  targetType: String(citation.target_type || 'content'),
  libraryId,
  docId: citation.doc_id,
  docTitle: citation.doc_title,
  pageIdx: Number(citation.page_idx || 0) || undefined,
  sectionPath: String(citation.section_path || '') || undefined,
  snippet: String(citation.snippet || '') || undefined,
  content: String(citation.content || '') || undefined,
  contentType: String(citation.content_type || '') || undefined,
  score: Number(citation.score || 0) || undefined,
  richMedia: normalizeCitationRichMedia({
    tableHtml: citation.rich_media?.table_html,
    mathContent: citation.rich_media?.math_content,
    imagePath: citation.rich_media?.image_path,
    imagePaths: citation.rich_media?.image_paths,
    richMediaOrder: citation.rich_media?.rich_media_order,
    sourceFileName: citation.rich_media?.source_file_name
  })
})

export const mapReferenceSearchCandidate = (
  item: Record<string, any>,
  payload: InlineCitationSearchPayload
): InlineCitationCandidate => ({
  label: String(item.label || payload.query || ''),
  triggerText: String(payload.query || ''),
  reference: {
    targetId: String(item.target_id || ''),
    targetType: String(item.target_type || 'content'),
    libraryId: String(item.library_id || payload.library_id || ''),
    docId: String(item.doc_id || ''),
    docTitle: String(item.doc_title || ''),
    pageIdx: Number(item.page_idx || 0) || undefined,
    sectionPath: String(item.section_path || '') || undefined,
    snippet: String(item.snippet || '') || undefined,
    content: String(item.content || '') || undefined,
    contentType: String(item.content_type || '') || undefined,
    score: Number(item.score || 0) || undefined,
    sourceVersion: String(item.source_version || '') || undefined,
    richMedia: normalizeCitationRichMedia({
      tableHtml: item.rich_media?.table_html,
      mathContent: item.rich_media?.math_content,
      imagePath: item.rich_media?.image_path,
      imagePaths: item.rich_media?.image_paths,
      richMediaOrder: item.rich_media?.rich_media_order,
      sourceFileName: item.rich_media?.source_file_name
    })
  }
})

export const cloneInlineCitationDraft = (value: InlineCitationDraftValue): InlineCitationDraftValue => ({
  content: value.content,
  citations: value.citations.map(citation => ({
    ...citation,
    range: { ...citation.range },
    reference: {
      ...citation.reference,
      richMedia: citation.reference.richMedia
        ? {
          ...citation.reference.richMedia,
          imagePaths: citation.reference.richMedia.imagePaths
            ? [...citation.reference.richMedia.imagePaths]
            : undefined,
          richMediaOrder: citation.reference.richMedia.richMediaOrder
            ? [...citation.reference.richMedia.richMediaOrder]
            : undefined
        }
        : undefined
    }
  }))
})
