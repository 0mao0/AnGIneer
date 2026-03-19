import type { KnowledgeTreeNode } from './tree'

export type KnowledgeStrategy = 'A_structured' | 'B_mineru_rag' | 'C_pageindex'

export type IngestStatus = 'idle' | 'processing' | 'completed' | 'failed'

export interface ParseTaskInfo {
  id: string
  library_id: string
  doc_id: string
  status: 'queued' | 'processing' | 'completed' | 'failed'
  progress: number
  stage: string
  error?: string
}

export interface StructuredIndexItem {
  id: string
  item_type: string
  title?: string
  content: string
  meta?: Record<string, any>
  order_index: number
}

export interface StructuredStats {
  total?: number
  strategies?: Partial<Record<KnowledgeStrategy, Record<string, number>>>
  [key: string]: any
}

export interface DocumentStorageManifest {
  doc_root: string
  source_file: string | null
  parsed_markdown: string | null
  edited_markdown: string | null
  assets_dir: string | null
  raw_dir: string | null
  middle_json: string | null
  mineru_blocks: string | null
  history_files: string[]
}

export interface DocBlockNode {
  id: string
  block_uid: string
  block_type: string
  page_idx: number
  block_seq: number
  plain_text: string
  bbox: [number, number, number, number] | null
  bbox_source: string
  derived_level: number | null
  title_path: string | null
  parent_uid: string | null
  derived_by: string
  confidence: number
  image_path: string | null
  table_html: string | null
  math_content: string | null
}

export interface DocBlockEdge {
  id: string
  from: string
  to: string
  kind: 'strong' | 'weak'
  label: string
  color: string
}

export interface DocBlocksGraph {
  nodes: DocBlockNode[]
  edges: DocBlockEdge[]
}

export interface DocBlocksGraphState {
  activeNodeId: string | null
  expandedNodeIds: Set<string>
  expandedGraphNodeIds: Set<string>
  viewMode: 'tree' | 'graph'
  viewportState: {
    x: number
    y: number
    scale: number
  } | null
}

export interface DocumentParsedWorkspaceEventMap {
  parse: [node: KnowledgeTreeNode]
  'save-content': [content: string]
  'change-strategy': [strategy: KnowledgeStrategy]
  'query-structured': [itemType?: string, keyword?: string]
  'rebuild-structured': [strategy: KnowledgeStrategy]
}

export interface PreviewIndexInteractionEventMap {
  toggle: [id: string]
  select: [id: string]
  'update-viewport': [state: { x: number; y: number; scale: number }]
}
