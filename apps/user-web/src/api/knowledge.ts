import type { DocumentResponse } from '@angineer/docs-ui'
import { docsApiClient } from '../../../shared/apiClient'

export const knowledgeApi = {
  getNodes: (libraryId: string = 'default', visible: boolean = false) =>
    docsApiClient.get('/knowledge/nodes', { params: { library_id: libraryId, visible } }),

  getLibraries: () => docsApiClient.get<{ id: string; name: string }[]>('/knowledge/libraries'),

  getDocument: (libraryId: string, docId: string) =>
    docsApiClient.get<DocumentResponse>(`/knowledge/document/${libraryId}/${docId}`),

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    docsApiClient.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId }),

  buildStructuredIndex: (libraryId: string, docId: string, strategy: string = 'doc_blocks_graph_v1') =>
    docsApiClient.post('/knowledge/parse/structured-index', { library_id: libraryId, doc_id: docId, strategy })
}

export default docsApiClient
