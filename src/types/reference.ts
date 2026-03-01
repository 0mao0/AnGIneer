export interface Reference {
  id: string
  type: 'document' | 'table' | 'formula' | 'figure'
  source: string
  title: string
  content: string
  location: ReferenceLocation
}

export interface ReferenceLocation {
  documentId: string
  page?: number
  blockId?: string
  section?: string
}

export interface ReferenceContext {
  id: string
  reference: Reference
  selectedText?: string
  timestamp: number
}

export interface CrossReference {
  fromId: string
  toId: string
  type: 'cites' | 'uses' | 'defines' | 'modifies'
  context?: string
}
