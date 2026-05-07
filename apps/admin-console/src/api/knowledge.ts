import type {
  KnowledgeStrategy,
  ParseTaskInfo,
  StructuredIndexItem,
  StructuredNodeUpdatePayload,
  StructuredBatchOperationPayload,
  StructuredStats,
  DocumentStorageManifest,
  DocumentResponse,
  KnowledgeParseOptions,
  LlmConfigOption,
  KnowledgeEvalDataset,
  KnowledgeEvalQuestionsResponse,
  KnowledgeEvalRunResponse
} from '@angineer/docs-ui'
import axios from 'axios'
import { getApiClientConfig, registerDataUnwrapInterceptor } from '../../../shared/apiClient'

export type {
  KnowledgeParseOptions,
  LlmConfigOption,
  KnowledgeEvalQuestion,
  KnowledgeEvalDataset,
  KnowledgeEvalSummary,
  KnowledgeEvalAnswerDetail,
  KnowledgeEvalRunResponse,
  KnowledgeEvalQuestionsResponse
} from '@angineer/docs-ui'

interface StructuredIndexResponse {
  doc_id: string
  strategy: KnowledgeStrategy
  count: number
  items: StructuredIndexItem[]
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

const api = registerDataUnwrapInterceptor(axios.create(getApiClientConfig({ baseURL: '/api' })))

api.interceptors.request.use((config: any) => {
  console.log('[API Request]:', config.method?.toUpperCase(), config.url, config.params || config.data)
  return config
})

export const knowledgeApi = {
  getLibraries: () => api.get('/knowledge/libraries'),
  createLibrary: (name: string, description: string) =>
    api.post('/knowledge/libraries', { library_id: 'default', name, description }),
  getLibrary: (libraryId: string) => api.get(`/knowledge/libraries/${libraryId}`),

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

  parseDocument: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  parseDocumentAsync: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  getParseTask: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}`) as Promise<ParseTaskInfo>,
  getLlmConfigs: () =>
    api.get('/llm_configs') as Promise<LlmConfigOption[]>,
  getEvalDatasets: () =>
    api.get('/knowledge/evals/datasets') as Promise<{ datasets: KnowledgeEvalDataset[] }>,
  getEvalQuestions: (datasetId?: string) =>
    api.get('/knowledge/evals/questions', {
      params: datasetId ? { dataset_id: datasetId } : undefined
    }) as Promise<KnowledgeEvalQuestionsResponse>,
  runEvalSuite: (datasetId?: string, cachedPredictions?: Record<string, any>) =>
    api.post('/knowledge/evals/run', {
      ...(datasetId ? { dataset_id: datasetId } : {}),
      ...(cachedPredictions ? { cached_predictions: cachedPredictions } : {})
    }, { timeout: 300000 }) as Promise<KnowledgeEvalRunResponse>,

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

  uploadDocument: (libraryId: string, file: File, parentId?: string) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('library_id', libraryId)
    if (parentId) formData.append('parent_id', parentId)
    return api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })
  },
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

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    api.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId }),
  getDocBlocksGraphSummary: (libraryId: string, docId: string) =>
    api.post('/knowledge/parse/doc-blocks-graph-summary', { library_id: libraryId, doc_id: docId })
}

export default api
