import axios from 'axios'
import type {
  KnowledgeStrategy,
  ParseTaskInfo,
  StructuredIndexItem,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  StructuredStats,
  DocumentStorageManifest
} from '@angineer/docs-ui'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

interface StructuredIndexResponse {
  doc_id: string
  strategy: KnowledgeStrategy
  count: number
  items: StructuredIndexItem[]
}

interface DocumentResponse {
  content: string
  storage: DocumentStorageManifest
  mineru_blocks?: Record<string, any>[]
  middle_data?: Record<string, any> | null
  graph_data?: { nodes: Record<string, any>[]; edges: Record<string, any>[] } | null
}

interface StructuredNodeUpdateResponse {
  doc_id: string
  block_id: string
  updated_fields: string[]
  node: Record<string, any>
}

interface StructuredBatchOperationResponse {
  doc_id: string
  operation: string
  block_ids: string[]
  target_block_id?: string | null
  created_block_ids?: string[]
  removed_block_ids?: string[]
  updated_block_ids?: string[]
  saved_segments: number
}

interface UndoStructuredOperationResponse {
  doc_id: string
  restored_block_ids: string[]
  saved_segments: number
}

interface DeleteNodePreviewResponse {
  node_id: string
  node_title: string
  node_type: string
  total_nodes: number
  folder_count: number
  document_count: number
  doc_ids: string[]
  doc_titles: string[]
  sample_doc_titles: string[]
}

export interface KnowledgeParseOptions {
  use_llm?: boolean
  llm_model?: string
}

export interface LlmConfigOption {
  name: string
  model: string
  configured: boolean
}

export interface KnowledgeEvalQuestion {
  question_id: string
  question: string
  task_type: string
  difficulty: string
  tags: string[]
  library_id?: string
  doc_ids?: string[]
  expected_route?: string
}

export interface KnowledgeEvalSummary {
  retrieval_score: number
  answer_health_score: number
  answer_correctness_score: number | null
  checked_answer_total: number
  overall_score: number
  text2sql_success_score: number
}

export interface KnowledgeEvalAnswerDetail {
  question_id: string
  question: string
  difficulty: string
  tags: string[]
  task_type?: string
  strategy?: string
  answer_non_empty?: number
  citation_hit?: number
  refusal_correct?: number
  answer_correct_checked?: boolean
  answer_correct?: number | null
  failed_correctness_checks?: Array<{ type?: string; keywords?: string[] }>
  answer?: string
  citations?: Array<{
    target_id: string
    doc_id: string
    doc_title: string
    page_idx: number
    section_path: string
    snippet: string
    score: number
  }>
}

export interface KnowledgeEvalRunResponse {
  generated_at: string
  questions: KnowledgeEvalQuestion[]
  report: {
    summary: KnowledgeEvalSummary
    answer: {
      total: number
      answer_non_empty_rate: number
      citation_hit_rate: number
      refusal_correct_rate: number
      correctness_checked_total: number
      answer_correctness_rate: number
      details: KnowledgeEvalAnswerDetail[]
    }
    retrieval: Record<string, any>
    text2sql: Record<string, any>
  }
}

api.interceptors.request.use(config => {
  console.log('[API Request]:', config.method?.toUpperCase(), config.url, config.params || config.data)
  return config
})

api.interceptors.response.use(
  response => {
    console.log('[API Response]:', response)
    return response.data
  },
  error => {
    console.error('[API Error]:', error.response?.status, error.response?.data || error.message)
    return Promise.reject(error)
  }
)

export const knowledgeApi = {
  // 知识库
  getLibraries: () => api.get('/knowledge/libraries'),
  createLibrary: (name: string, description: string) => 
    api.post('/knowledge/libraries', { library_id: 'default', name, description }),
  getLibrary: (libraryId: string) => api.get(`/knowledge/libraries/${libraryId}`),

  // 节点
  getNodes: (libraryId: string = 'default', visible: boolean = false) => 
    api.get('/knowledge/nodes', { params: { library_id: libraryId, visible } }),
  createNode: (data: {
    title: string
    node_type: string
    library_id?: string
    parent_id?: string
    visible?: boolean
    sort_order?: number
  }) => api.post('/knowledge/nodes', data),
  updateNode: (nodeId: string, data: Record<string, any>) => 
    api.patch(`/knowledge/nodes/${nodeId}`, data),
  getDeleteNodePreview: (nodeId: string) =>
    api.get(`/knowledge/nodes/${nodeId}/delete-preview`) as Promise<DeleteNodePreviewResponse>,
  deleteNode: (nodeId: string) => api.delete(`/knowledge/nodes/${nodeId}`),

  // 文档解析
  parseDocument: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) => 
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  parseDocumentAsync: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  getParseTask: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}`) as Promise<ParseTaskInfo>,
  getLlmConfigs: () =>
    api.get('/llm_configs') as Promise<LlmConfigOption[]>,
  getEvalQuestions: () =>
    api.get('/knowledge/evals/questions') as Promise<{ questions: KnowledgeEvalQuestion[] }>,
  runEvalSuite: () =>
    api.post('/knowledge/evals/run', undefined, { timeout: 300000 }) as Promise<KnowledgeEvalRunResponse>,

  // 策略
  getDocStrategy: (docId: string) => api.get(`/knowledge/strategies/${docId}`),
  setDocStrategy: (docId: string, strategy: KnowledgeStrategy) =>
    api.put(`/knowledge/strategies/${docId}`, { strategy }),
  buildStructuredIndex: (libraryId: string, docId: string, strategy: KnowledgeStrategy) =>
    api.post('/knowledge/structured/index', { library_id: libraryId, doc_id: docId, strategy }),
  getStructuredIndex: (
    docId: string,
    strategy: KnowledgeStrategy,
    itemType?: string,
    keyword?: string
  ) => api.get(`/knowledge/structured/${docId}`, { params: { strategy, item_type: itemType, keyword } }) as Promise<StructuredIndexResponse>,
  getStructuredStats: (docId: string) => api.get(`/knowledge/structured/stats/${docId}`) as Promise<StructuredStats>,

  // 上传文档
  uploadDocument: (libraryId: string, file: File, parentId?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('library_id', libraryId)
    if (parentId) formData.append('parent_id', parentId)
    return api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
  // 文档内容
  getDocument: (libraryId: string, docId: string) => 
    api.get(`/knowledge/document/${libraryId}/${docId}`) as Promise<DocumentResponse>,
  updateDocument: (libraryId: string, docId: string, content: string) => 
    api.put(`/knowledge/document/${libraryId}/${docId}`, { content }),
  updateDocumentBlock: (libraryId: string, docId: string, payload: StructuredNodeUpdatePayload) =>
    api.patch(`/knowledge/document/${libraryId}/${docId}/blocks/${encodeURIComponent(payload.blockId)}`, payload) as Promise<StructuredNodeUpdateResponse>,
  batchOperateDocumentBlocks: (libraryId: string, docId: string, payload: StructuredBatchOperationPayload) =>
    api.post(`/knowledge/document/${libraryId}/${docId}/blocks/batch`, payload) as Promise<StructuredBatchOperationResponse>,
  undoLastDocumentBlockOperation: (libraryId: string, docId: string) =>
    api.post(`/knowledge/document/${libraryId}/${docId}/blocks/undo`) as Promise<UndoStructuredOperationResponse>,
  getDocumentStorage: (libraryId: string, docId: string) =>
    api.get(`/knowledge/storage/${libraryId}/${docId}`) as Promise<{
      library_id: string
      doc_id: string
      storage: DocumentStorageManifest
    }>,

  // 文档块图谱
  getDocBlocksGraph: (libraryId: string, docId: string) =>
    api.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId })
}

export default api
