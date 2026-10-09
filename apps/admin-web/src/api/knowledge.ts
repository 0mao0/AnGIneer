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

/** 总览 tab：按组聚合的库清单（后端 /knowledge/libraries/groups 直出） */
export interface LibraryGroupItem {
  group_name: string
  is_default_group: boolean
  known_group: boolean
  /** 自定义组的显示名（内置组为空串，前端用 GROUP_LABELS） */
  display_name?: string
  libraries: {
    id: string
    name: string
    description?: string | null
    collection?: string
    status?: string
    doc_count: number
  }[]
}

// ---- 知识库拆分/合并迁移（kb-split-merge 计划 Task 14）----
// 拆分目的地二选一：new_library_id=拆到新库；target_library_id=拆出去并入已有库。
// 合并只认 target_library_id（整库并入，源库退役）。
export interface MigrationSubmitInput {
  op: 'split' | 'merge'
  source_library_id: string
  target_library_id?: string
  new_library_id?: string
  new_name?: string
  doc_ids?: string[]
}
export interface MigrationPreview {
  op: string
  source_library_id: string
  target_library_id: string
  doc_ids: string[]
  new_name: string
  /** 拆到新库时=新库 ID；并入已有库时为空（目的地形态判据） */
  new_library_id?: string
  counts: Record<string, any>
  eval_refs: { datasets: { dataset_id: string; title: string }[]; question_count: number; questions_on_moved_docs?: number }
  blockers: string[]
  digest: string
}
export interface MigrationTask {
  id: string
  op: string
  params: Record<string, any>
  status: 'running' | 'cancelling' | 'completed' | 'failed' | 'cancelled' | 'cancel_failed' | 'interrupted' | 'switch_reload_failed'
  stage: string
  progress_done: number
  progress_total: number
  stage_message?: string
  error?: string
  steps: { at: string; stage: string; step: string; status: string }[]
  migrated_doc_ids: string[]
  preview?: MigrationPreview
  verify?: { ok: boolean; mismatches: string[] }
  rollback_deadline?: string
  created_at: string
}

/** 迁移任务终态（不再变化）。抽屉停轮询与总览刷新判断共用这一处，避免两份清单漂移。 */
export const MIGRATION_TERMINAL_STATUSES = [
  'completed', 'failed', 'cancelled', 'cancel_failed', 'interrupted', 'switch_reload_failed',
] as const

export function isMigrationTerminal(status?: string): boolean {
  return !!status && (MIGRATION_TERMINAL_STATUSES as readonly string[]).includes(status)
}
export interface LibraryVolume {
  library_id: string
  name: string
  status: string
  docs: number
  chunks: number
  vectors: number
  disk_bytes: number
  updated_at?: string
}

// ---- 语料包导出（docs/design-kb-export-ui.md）----
// 服务端不落盘：边读边打包边出网。进度以后端 status 为准（字节口径），前端只展示。
export interface ExportPreview {
  libraries: { library_id: string; name: string; group_name: string; collection: string }[]
  files_bytes: number
  file_count: number
  sqlite_bytes: number
  snapshot_estimate: number
  total_estimate: number
  /** 同组未全选的警告（共用 sqlite，包内仍含未勾选库的索引数据） */
  warnings: string[]
  /** 同组未选中的库（含空库）；空库不在可选清单，不能建议「全选」 */
  peers: { library_id: string; name: string }[]
  selectable_library_ids: string[]
  active_task_id: string | null
}
export interface ExportStatus {
  task_id: string
  status: 'running' | 'completed' | 'failed' | 'cancelled' | 'unknown'
  stage: string
  message: string
  bytes_out: number
  total_bytes: number
  percent: number
  error: string
}

export const knowledgeApi = {
  getLibraries: () => api.get('/knowledge/libraries'),
  createLibrary: (name: string, description: string = '', groupName: string = '') =>
    api.post('/knowledge/libraries', {
      name,
      description,
      ...(groupName ? { group_name: groupName } : {}),
    }) as Promise<{ id: string; name: string }>,
  getLibraryGroups: () => api.get('/knowledge/libraries/groups') as Promise<LibraryGroupItem[]>,
  /** 建自定义库组（slug 非法/撞内置组名 → 400，detail 为中文原因） */
  createLibraryGroup: (groupName: string, displayName: string = '') =>
    api.post('/knowledge/libraries/groups', {
      group_name: groupName,
      display_name: displayName,
    }) as Promise<{ group_name: string; display_name: string }>,
  getLibrary: (libraryId: string) => api.get(`/knowledge/libraries/${libraryId}`),
  updateLibrary: (libraryId: string, data: { name?: string; description?: string; group_name?: string }) =>
    api.patch(`/knowledge/libraries/${libraryId}`, data) as Promise<{ id: string; name: string }>,
  deleteLibrary: (libraryId: string) =>
    api.delete(`/knowledge/libraries/${libraryId}`) as Promise<{ status: string; library_id: string }>,

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
  batchSoftDeleteNodes: (nodeIds: string[]) =>
    api.post('/knowledge/nodes/batch-soft-delete', { node_ids: nodeIds }) as Promise<
      { status: string; deleted: number; failed: Array<{ node_id: string; reason: string }> }
    >,
  forceDeleteNode: (nodeId: string) =>
    api.delete(`/knowledge/nodes/${nodeId}/force`) as Promise<{ status: string; message: string }>,
  cancelParseTask: (taskId: string) =>
    api.post(`/knowledge/parse/${taskId}/cancel`) as Promise<{ status: string; task_id: string; message: string }>,
  retryParseTask: (docId: string) =>
    api.post('/knowledge/parse/retry', { doc_id: docId }) as Promise<{ status: string; task_id: string; doc_id: string; message: string }>,
  batchRetryParseTasks: (docIds: string[]) =>
    api.post('/knowledge/parse/batch-retry', { doc_ids: docIds }) as Promise<{
      status: string;
      started: number;
      failed: number;
      results: Array<{ doc_id: string; task_id: string }>;
      errors: Array<{ doc_id: string; reason: string }>;
    }>,

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

  uploadDocument: (
    libraryId: string,
    file: File,
    parentId?: string,
    onProgress?: (percent: number) => void
  ) => {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('library_id', libraryId)
    if (parentId) formData.append('parent_id', parentId)
    return api.post('/knowledge/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      // 大文件上传：至少 2 分钟，每 MB 再加 5s，避免 30s 默认超时掐断
      timeout: Math.max(120000, Math.ceil(file.size / 1024 / 1024) * 5000),
      ...(onProgress
        ? {
            onUploadProgress: (e: { loaded: number; total?: number }) => {
              const percent = e.total ? Math.min(99, Math.round((e.loaded / e.total) * 100)) : 0
              onProgress(percent)
            },
          }
        : {}),
    })
  },
  getDocument: (libraryId: string, docId: string, options?: { includeContent?: boolean }) =>
    api.get(`/knowledge/document/${libraryId}/${docId}`, {
      // include_content=false 只回 storage：预览先拿 render_pdf 起 PDF，不被整份 markdown 传输挡住
      params: options?.includeContent === false ? { include_content: false } : undefined
    }) as Promise<DocumentResponse>,
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

  downloadDocFile: (docId: string, kind: 'source' | 'pdf') =>
    api.get(`/knowledge/documents/${docId}/download`, {
      params: { kind },
      responseType: 'blob',
    }) as Promise<Blob>,

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
      source_doc_name: string
      proposed_doc_id: string
      proposed_doc_name: string
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
      source_doc_name: string
      proposed_doc_id: string
      proposed_doc_name: string
      created_at: string
    }[]>,
  createGraphEntity: (data: {
    library_id: string
    name: string
    layer: string
    aliases?: string[]
    description?: string
    source_doc?: string
    source_clause?: string
  }) => api.post('/graph/entities', data) as Promise<{
    entity_id: string
    name: string
    layer: string
    aliases: string[]
    status: string
  }>,
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
  batchHardDeleteRecords: (recordIds: number[]) =>
    api.post('/knowledge/records/batch-hard-delete', { record_ids: recordIds }) as Promise<
      { status: string; deleted: number; failed: Array<{ record_id: number; reason: string }> }
    >,

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

  // ---- 知识库拆分/合并迁移 ----
  previewMigration: (data: MigrationSubmitInput) =>
    api.post('/knowledge/migrations/preview', data) as Promise<MigrationPreview>,
  submitMigration: (data: MigrationSubmitInput & { preview_digest: string }) =>
    api.post('/knowledge/migrations', data) as Promise<{ task_id: string; status: string }>,
  listMigrations: () => api.get('/knowledge/migrations') as Promise<{ tasks: MigrationTask[] }>,
  getMigration: (taskId: string) =>
    api.get(`/knowledge/migrations/${taskId}`) as Promise<MigrationTask>,
  cancelMigration: (taskId: string) =>
    api.post(`/knowledge/migrations/${taskId}/cancel`) as Promise<{ status: string; message: string }>,
  resumeMigration: (taskId: string) =>
    api.post(`/knowledge/migrations/${taskId}/resume`) as Promise<{ status: string; message: string }>,
  rollbackMigration: (taskId: string) =>
    api.post(`/knowledge/migrations/${taskId}/rollback`) as Promise<{ task_id: string; message: string }>,
  getMigrationAudit: (params?: { offset?: number; limit?: number }) =>
    api.get('/knowledge/migrations/audit', { params }) as Promise<{ entries: any[]; total: number }>,
  /** 体量看板：默认走服务端 5 分钟缓存；refresh=true（面板刷新按钮）强制重扫 */
  getLibraryVolumes: (refresh = false) =>
    api.get('/knowledge/migrations/volumes', refresh ? { params: { refresh: 1 } } : undefined) as Promise<{ volumes: LibraryVolume[]; thresholds: { docs: number; vectors: number; disk_bytes: number } }>,

  // ---- 语料包导出（服务端流式，不落盘）----
  previewExport: (libraries: string[]) =>
    api.post('/knowledge/exports/preview', { libraries }) as Promise<ExportPreview>,
  /** 一次性下载凭据：浏览器「另存为」/原生下载带不上 Authorization 头，用票换下载权（120s、单次） */
  issueExportTicket: (taskId: string, libraries: string[]) =>
    api.post('/knowledge/exports/ticket', { task_id: taskId, libraries }) as Promise<{ ticket: string; expires_in: number }>,
  getExportStatus: (taskId: string) =>
    api.get(`/knowledge/exports/${taskId}/status`) as Promise<ExportStatus>,
  cancelExport: (taskId: string) =>
    api.post(`/knowledge/exports/${taskId}/cancel`) as Promise<{ status: string; message: string }>,
  /** 导出流地址（供 <a download> 或 fetch 直取；ticket 必带，否则需 Bearer） */
  exportStreamUrl: (taskId: string, libraries: string[], ticket: string) =>
    `/api/knowledge/exports/stream?task_id=${encodeURIComponent(taskId)}` +
    `&libraries=${encodeURIComponent(libraries.join(','))}&ticket=${encodeURIComponent(ticket)}`,
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
