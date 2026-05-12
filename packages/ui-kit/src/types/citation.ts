export interface CitationRichMediaOrderItem {
  type: 'image' | 'table' | 'math'
  path?: string
}

export interface CitationRichMediaValue {
  tableHtml?: string
  mathContent?: string
  imagePath?: string
  imagePaths?: string[]
  richMediaOrder?: CitationRichMediaOrderItem[]
  sourceFileName?: string
}

export interface CitationReference {
  targetId: string
  targetType: string
  libraryId?: string
  docId: string
  docTitle: string
  pageIdx?: number
  sectionPath?: string
  snippet?: string
  content?: string
  contentType?: string
  score?: number
  richMedia?: CitationRichMediaValue
  sourceVersion?: string
}

export interface CitationRange {
  start: number
  end: number
}

export interface CitationBinding {
  id: string
  label: string
  triggerText: string
  range: CitationRange
  reference: CitationReference
  status?: 'active' | 'mismatch'
}

export interface InlineCitationDraftValue {
  content: string
  citations: CitationBinding[]
}

export interface InlineCitationCandidate {
  label: string
  triggerText?: string
  reference: CitationReference
}

export interface InlineCitationSearchPayload {
  library_id: string
  query: string
  limit?: number
  types?: string[]
  current_doc_id?: string
}
