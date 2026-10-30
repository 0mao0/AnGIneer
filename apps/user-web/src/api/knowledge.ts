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
    // 大文档的整本文本块数据（doc_blocks_graph）可达十几 MB，默认 30s 闸门会误杀；
    // 只在用户点开树形/图谱页签或点引用角标时才拉这一份。按请求放宽到 3 分钟，失败可重试
    docsApiClient.post('/knowledge/parse/doc-blocks-graph', { library_id: libraryId, doc_id: docId }, { timeout: 180000 }),

  /** 页级切片：只取目标页 ±2 页的文本块（几十 KB），供引用定位的高亮框用（2026-10-30） */
  getDocBlocksGraphPages: (libraryId: string, docId: string, pageFrom: number, pageTo: number) =>
    docsApiClient.post(
      '/knowledge/parse/doc-blocks-graph',
      { library_id: libraryId, doc_id: docId, page_from: pageFrom, page_to: pageTo },
      { timeout: 30000 }
    )
}

export default docsApiClient
