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
    api.post('/knowledge/libraries', null, { params: { name, description } }),
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
  }) => api.post('/knowledge/nodes', null, { params: data }),
  updateNode: (nodeId: string, data: Record<string, any>) => {
    const params = new URLSearchParams()
    Object.entries(data).forEach(([key, value]) => {
      if (value !== undefined && value !== null) {
        params.append(key, String(value))
      } else if (value === null) {
        params.append(key, '')
      }
    })
    return api.patch(`/knowledge/nodes/${nodeId}?${params.toString()}`)
  },
  deleteNode: (nodeId: string) => api.delete(`/knowledge/nodes/${nodeId}`),

  // 文档解析
  parseDocument: (libraryId: string, docId: string, filePath?: string) => 
    api.post('/knowledge/parse', null, { params: { library_id: libraryId, doc_id: docId, file_path: filePath } }),
  parseDocumentAsync: (libraryId: string, docId: string, filePath?: string) =>
    api.post('/knowledge/parse', null, { params: { library_id: libraryId, doc_id: docId, file_path: filePath } }),
  getParseTask: (taskId: string) =>
    api.get(`/knowledge/parse/tasks/${taskId}`) as Promise<ParseTaskInfo>,

  // 策略
  getDocStrategy: (docId: string) => api.get(`/knowledge/strategies/${docId}`),
  setDocStrategy: (docId: string, strategy: KnowledgeStrategy) =>
    api.put(`/knowledge/strategies/${docId}`, null, { params: { strategy } }),
  buildStructuredIndex: (libraryId: string, docId: string, strategy: KnowledgeStrategy) =>
    api.post('/knowledge/structured/index', null, { params: { library_id: libraryId, doc_id: docId, strategy } }),
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
    api.post('/knowledge/rag/query', null, { params: { question, library_id: libraryId, k, use_llm: useLlm } }),
  ragBuild: (libraryId: string, docIds: string[]) => 
    api.post('/knowledge/rag/build', null, { params: { library_id: libraryId, doc_ids: docIds } }),

  // 文档内容
  getDocument: (libraryId: string, docId: string) => 
    api.get(`/knowledge/document/${libraryId}/${docId}`) as Promise<DocumentResponse>,
  updateDocument: (libraryId: string, docId: string, content: string) => 
    api.put(`/knowledge/document/${libraryId}/${docId}`, null, { params: { content } }),
  getDocumentStorage: (libraryId: string, docId: string) =>
    api.get(`/knowledge/storage/${libraryId}/${docId}`) as Promise<{
      library_id: string
      doc_id: string
      storage: DocumentStorageManifest
    }>,
  reorganizeStorage: () => api.post('/knowledge/storage/reorganize')
}

export default api
