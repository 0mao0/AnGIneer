import type { DocumentResponse } from '@angineer/docs-ui'
import { docsApiClient } from '../../../shared/apiClient'

export const knowledgeApi = {
  getLibraries: () => docsApiClient.get<{ id: string; name: string }[]>('/knowledge/libraries'),

  getDocument: (libraryId: string, docId: string, options?: { includeContent?: boolean }) =>
    docsApiClient.get<DocumentResponse>(`/knowledge/document/${libraryId}/${docId}`, {
      // include_content=false 只回 storage：预览面板先拿 render_pdf 起 PDF，不被整份 markdown 传输挡住
      params: options?.includeContent === false ? { include_content: false } : undefined
    }),

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    docsApiClient.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId })
}

export default docsApiClient
