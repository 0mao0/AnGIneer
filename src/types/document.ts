export interface Document {
  id: string
  title: string
  source: string
  libraryId: string
  content: string
  blocks: DocumentBlock[]
  metadata: DocumentMetadata
}

export interface DocumentBlock {
  id: string
  type: 'text' | 'table' | 'formula' | 'figure' | 'heading'
  content: string
  location: BlockLocation
  enhancedData?: Record<string, any>
  references?: string[]
}

export interface BlockLocation {
  page: number
  x: number
  y: number
  width: number
  height: number
}

export interface DocumentMetadata {
  author?: string
  version?: string
  publishDate?: string
  category?: string
  tags?: string[]
  schema_version?: number // 新增：Schema 版本号，用于数据迁移和兼容性处理
}

export interface Library {
  id: string
  name: string
  description?: string
  documentCount: number
  createdAt: string
  updatedAt: string
}
