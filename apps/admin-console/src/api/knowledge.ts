import axios from 'axios'
import type {
  KnowledgeStrategy,
  ParseTaskInfo,
  StructuredIndexItem,
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
  deleteNode: (nodeId: string) => api.delete(`/knowledge/nodes/${nodeId}`),

  // 文档解析
  parseDocument: (libraryId: string, docId: string, filePath?: string) => 
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath }),
  parseDocumentAsync: (libraryId: string, docId: string, filePath?: string) =>
    api.post('/knowledge/parse', { library_id: libraryId, doc_id: docId, file_path: filePath }),
  getParseTask: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}`) as Promise<ParseTaskInfo>,

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

  // RAG
  ragQuery: (question: string, libraryId: string = 'default', k: number = 4, useLlm: boolean = true) => 
    api.post('/knowledge/rag/query', { question, library_id: libraryId, k, use_llm: useLlm }),
  ragBuild: (libraryId: string, docIds: string[]) => 
    api.post('/knowledge/rag/build', { library_id: libraryId, doc_ids: docIds }),

  // 文档内容
  getDocument: (libraryId: string, docId: string) => 
    api.get(`/knowledge/document/${libraryId}/${docId}`) as Promise<DocumentResponse>,
  updateDocument: (libraryId: string, docId: string, content: string) => 
    api.put(`/knowledge/document/${libraryId}/${docId}`, { content }),
  getDocumentStorage: (libraryId: string, docId: string) =>
    api.get(`/knowledge/storage/${libraryId}/${docId}`) as Promise<{
      library_id: string
      doc_id: string
      storage: DocumentStorageManifest
    }>,
  reorganizeStorage: () => api.post('/knowledge/storage/reorganize'),

  // 文档块图谱
  getDocBlocksGraph: (libraryId: string, docId: string) =>
    api.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId })
}

export default api
