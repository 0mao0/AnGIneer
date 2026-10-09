import type { DocumentResponse } from '@angineer/docs-ui'
import { docsApiClient } from '../../../shared/apiClient'

/** 按组聚合的库清单（/knowledge/libraries/groups 直出；内置组 display_name 为空串，前端补显示名） */
export interface LibraryGroupItem {
  group_name: string
  display_name?: string
  libraries: { id: string; name: string }[]
}

export const knowledgeApi = {
  getLibraries: () => docsApiClient.get<{ id: string; name: string; group_name?: string }[]>('/knowledge/libraries'),

  getLibraryGroups: () => docsApiClient.get<LibraryGroupItem[]>('/knowledge/libraries/groups'),

  getDocument: (libraryId: string, docId: string, options?: { includeContent?: boolean }) =>
    docsApiClient.get<DocumentResponse>(`/knowledge/document/${libraryId}/${docId}`, {
      // include_content=false 只回 storage：预览面板先拿 render_pdf 起 PDF，不被整份 markdown 传输挡住
      params: options?.includeContent === false ? { include_content: false } : undefined
    }),

  getDocBlocksGraph: (libraryId: string, docId: string) =>
    docsApiClient.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId })
}

export default docsApiClient
