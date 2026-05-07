import type { DocumentResponse } from '@angineer/docs-ui'
import axios from 'axios'
import { getApiClientConfig, registerDataUnwrapInterceptor } from '../../../shared/apiClient'

const api = registerDataUnwrapInterceptor(axios.create(getApiClientConfig({ baseURL: '/api' })))

export const knowledgeApi = {
  getNodes: (libraryId: string = 'default', visible: boolean = false) =>
    api.get('/knowledge/nodes', { params: { library_id: libraryId, visible } }),

  getDocument: (libraryId: string, docId: string) =>
    api.get(`/knowledge/document/${libraryId}/${docId}`) as Promise<DocumentResponse>,

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    api.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId }),

  buildStructuredIndex: (libraryId: string, docId: string, strategy: string = 'doc_blocks_graph_v1') =>
    api.post('/knowledge/parse/structured-index', { library_id: libraryId, doc_id: docId, strategy })
}

export default api
