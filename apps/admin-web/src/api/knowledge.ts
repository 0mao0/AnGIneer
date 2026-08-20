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
import { docsApiClient, aichatApiClient } from '../../../shared/apiClient'

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

const api = docsApiClient

export const knowledgeApi = {
  getLibraries: () => api.get('/knowledge/libraries'),
  createLibrary: (name: string, description: string) =>
    api.post('/knowledge/libraries', { library_id: 'default', name, description }),
  getLibrary: (libraryId: string) => api.get(`/knowledge/libraries/${libraryId}`),

  getNodes: (libraryId?: string, visible: boolean = false) =>
    api.get('/knowledge/nodes', { params: { visible, ...(libraryId ? { library_id: libraryId } : {}) } }),
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
  softDeleteNode: (nodeId: string) =>
    api.delete(`/knowledge/nodes/${nodeId}/soft-delete`) as Promise<{ status: string; message: string; affected: number }>,
  forceDeleteNode: (nodeId: string) =>
    api.delete(`/knowledge/nodes/${nodeId}/force`) as Promise<{ status: string; message: string }>,
  cancelParseTask: (taskId: string) =>
    api.post(`/knowledge/parse/${taskId}/cancel`) as Promise<{ status: string; task_id: string; message: string }>,
  retryParseTask: (docId: string) =>
    api.post('/knowledge/parse/retry', { doc_id: docId }) as Promise<{ status: string; task_id: string; doc_id: string; message: string }>,

  parseDocument: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  parseDocumentAsync: (libraryId: string, docId: string, filePath?: string, parseOptions?: KnowledgeParseOptions) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath, parse_options: parseOptions }),
  getParseTask: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}`) as Promise<ParseTaskInfo>,
  getLlmConfigs: () =>
    aichatApiClient.get('/llm_configs') as Promise<LlmConfigOption[]>,
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
    api.post('/knowledge/parse/doc-blocks-graph-summary', { library_id: libraryId, doc_id: docId }),
  getGraphSnapshot: (params: { libraryId?: string; docId?: string; viewMode?: 'doc' | 'global' }) => {
    const query = params.viewMode === 'doc' && params.libraryId && params.docId
      ? { library_id: params.libraryId, doc_id: params.docId }
      : {}
    return api.get('/graph/snapshot', { params: query }) as Promise<{
      stats: any
      entities: any[]
      relations: any[]
    }>
  },
  buildGraphFromDoc: (libraryId: string, docId: string, enableLlmExtraction: boolean) =>
    api.post('/graph/build/from-doc', {
      library_id: libraryId,
      doc_id: docId,
      enable_llm_extraction: enableLlmExtraction,
    }) as Promise<{
      packets_processed: number
      total_entities_found: number
      total_relations_added: number
      snapshot: { stats: any; entities: any[]; relations: any[] }
    }>,
  getPendingGraphEntities: (libraryId: string) =>
    api.get('/graph/entities/pending', { params: { library_id: libraryId } }) as Promise<{
      entity_id: string
      name: string
      layer: string
      aliases: string[]
      source_clause: string
      source_doc: string
      proposed_doc_id: string
      created_at: string
    }[]>,
  getAllGraphEntities: (libraryId: string) =>
    api.get('/graph/entities/all', { params: { library_id: libraryId } }) as Promise<{
      entity_id: string
      name: string
      layer: string
      aliases: string[]
      status: 'approved' | 'pending' | 'rejected'
      source_clause: string
      source_doc: string
      proposed_doc_id: string
      created_at: string
    }[]>,
  approveGraphEntity: (entityId: string, reviewer?: string) =>
    api.post(`/graph/entities/${entityId}/approve`, { reviewer: reviewer || 'admin' }) as Promise<{ status: string }>,
  rejectGraphEntity: (entityId: string, reason: string, reviewer?: string) =>
    api.post(`/graph/entities/${entityId}/reject`, { reason, reviewer: reviewer || 'admin' }) as Promise<{
      status: string
      rescheduled_docs: Array<[string, string]>
    }>,
  deleteGraphEntity: (entityId: string) =>
    api.delete(`/graph/entities/${entityId}`) as Promise<{
      status: string
      rescheduled_docs: Array<[string, string]>
    }>,
  getDeletedGraphEntities: (libraryId: string) =>
    api.get('/graph/entities/deleted', { params: { library_id: libraryId } }) as Promise<{
      library_id: string
      name: string
      deleted_at: string
    }[]>,
  restoreDeletedGraphEntity: (libraryId: string, name: string) =>
    api.post('/graph/entities/deleted/restore', { library_id: libraryId, name }) as Promise<{ status: string }>,

  listRecords: (params?: {
    status?: string
    uploaded_by?: string
    show_deleted?: boolean
    library_id?: string
    start_date?: string
    end_date?: string
    limit?: number
    offset?: number
  }) => api.get('/knowledge/records', { params }) as Promise<{
    status: string
    data: ParseRecordItem[]
    total: number
  }>,

  cleanOrphanedRecords: () =>
    api.post('/knowledge/records/clean-orphaned') as Promise<{ status: string; message: string }>,

  restoreRecord: (recordId: number) =>
    api.put(`/knowledge/records/${recordId}/restore`) as Promise<{ status: string; message: string }>,

  hardDeleteRecord: (recordId: number) =>
    api.delete(`/knowledge/records/${recordId}/hard-delete`) as Promise<{ status: string; message: string }>,

  getTaskSteps: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}/steps`) as Promise<{ status: string; data: any[] }>,

  getDocStages: (docId: string) =>
    api.get(`/knowledge/documents/${docId}/stages`) as Promise<{
      doc_id: string
      stages: {
        stage: string
        status: string
        error: string
        message: string
        started_at: string
        finished_at: string
        updated_at: string
        backend?: string
        page_count?: number
        is_scanned?: boolean
        outputs?: { dir?: string; raw_dir?: string; items: { name: string; exists: boolean; isNew: boolean; isDir: boolean; childOfRaw?: boolean }[] }
        steps?: { step: string; status: string; detail?: string }[]
      }[]
    }>,

  retryDocStage: (docId: string, stageKey: string) =>
    api.post(`/knowledge/documents/${docId}/stages/${stageKey}/retry`) as Promise<{ status: string; task_id: string }>,
}

export interface ParseRecordItem {
  id: number
  doc_id: string
  task_id: string
  uploaded_by: string
  api_key_id: number | null
  api_key_name?: string
  file_name: string
  file_format: string
  file_size: number
  page_count?: number | null
  status: string
  error: string | null
  created_at: string
  file_status?: string
}

export default api
