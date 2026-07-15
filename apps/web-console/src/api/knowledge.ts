import type { DocumentResponse } from '@angineer/docs-ui'
import { sharedApiClient } from '../../../shared/createApiClient'

export const knowledgeApi = {
  getNodes: (libraryId: string = 'default', visible: boolean = false) =>
    sharedApiClient.get('/knowledge/nodes', { params: { library_id: libraryId, visible } }),

  getDocument: (libraryId: string, docId: string) =>
    sharedApiClient.get<DocumentResponse>(`/knowledge/document/${libraryId}/${docId}`),

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    sharedApiClient.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId }),

  buildStructuredIndex: (libraryId: string, docId: string, strategy: string = 'doc_blocks_graph_v1') =>
    sharedApiClient.post('/knowledge/parse/structured-index', { library_id: libraryId, doc_id: docId, strategy })
}

export default sharedApiClient
