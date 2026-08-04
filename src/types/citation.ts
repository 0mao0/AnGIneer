/**
 * 引用相关类型（本地化自 @angineer/ui-kit，docs-ui 不再依赖 ui-kit）。
 */

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
  pageLabel?: string
  sectionPath?: string
  snippet?: string
  content?: string
  contentType?: string
  score?: number
  richMedia?: CitationRichMediaValue
  sourceVersion?: string
}
