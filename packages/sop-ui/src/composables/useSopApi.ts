import type { InlineCitationSearchPayload } from '@angineer/ui-kit'
import type { RawSopData, SopData, SopFolder, SopListItem } from '../types/sop'
import { normalizeSopData, serializeSopData } from '../types/sop'
import { sharedApiClient, FORM_DATA_CONFIG } from '../../../../apps/shared/createApiClient'
import type { ApiErrorDetail } from '../../../../apps/shared/types'
import type { AxiosRequestConfig } from 'axios'

const SOP_PREFIX = '/sops'
const KNOWLEDGE_PREFIX = '/knowledge'

async function sopGet<T = any>(url: string): Promise<T> {
  return sharedApiClient.get(url)
}

async function sopRequest<T = any>(url: string, method: string, body?: any): Promise<T> {
  const config: AxiosRequestConfig = {}
  if (body !== undefined) {
    config.data = body
  }
  return sharedApiClient.request<T>({ url, method, ...config })
}

async function sopFormRequest<T = any>(url: string, method: string, body: FormData): Promise<T> {
  return sharedApiClient.request<T>({ url, method, data: body, ...FORM_DATA_CONFIG })
}

interface KnowledgeNodeItem {
  id: string
  title: string
  type: string
  parent_id?: string | null
  file_path?: string
  strategy?: string
}

interface StructuredIndexItem {
  uid: string
  block_type?: string
  text?: string
  title?: string
}

interface SopDeletePreview {
  target_id: string
  target_title: string
  target_type: 'sop' | 'folder'
  folder_count: number
  document_count: number
  total_nodes: number
  sample_titles: string[]
}

export const sopApi = {
  listSops: (): Promise<{ sops: SopListItem[] }> => sopGet(SOP_PREFIX),

  getSop: async (id: string): Promise<SopData> => {
    const data = await sopGet<RawSopData>(`${SOP_PREFIX}/${id}`)
    return normalizeSopData(data)
  },

  createSop: (data: Partial<SopData> & { name_zh: string }): Promise<{ status: string; id: string }> =>
    sopRequest(SOP_PREFIX, 'POST', data),

  saveSop: (id: string, data: Partial<SopData>): Promise<{ status: string; id: string }> => {
    const payload = data.steps ? serializeSopData(data as SopData) : data
    return sopRequest(`${SOP_PREFIX}/${id}`, 'PUT', payload)
  },

  updateSopMeta: (
    id: string,
    data: Partial<Pick<SopData, 'name_zh' | 'name_en' | 'description' | 'folder_id' | 'sort_order'>>
  ): Promise<{ status: string; id: string }> => sopRequest(`${SOP_PREFIX}/${id}`, 'PUT', data),

  deleteSop: (id: string): Promise<{ status: string }> =>
    sopRequest(`${SOP_PREFIX}/${id}`, 'DELETE'),

  getSopDeletePreview: (id: string): Promise<SopDeletePreview> =>
    sopGet(`${SOP_PREFIX}/${id}/delete-preview`),

  getFolders: (): Promise<{ folders: SopFolder[] }> => sopGet(`${SOP_PREFIX}/folders/list`),

  createFolder: (data: { title: string; parent_folder_id?: string | null; sort_order?: number }): Promise<{ status: string; folder_id: string }> =>
    sopRequest(`${SOP_PREFIX}/folders`, 'POST', data),

  updateFolder: (folderId: string, data: { title?: string; parent_folder_id?: string | null; sort_order?: number }): Promise<{ status: string }> =>
    sopRequest(`${SOP_PREFIX}/folders/${folderId}`, 'PATCH', data),

  deleteFolder: (folderId: string): Promise<{ status: string }> =>
    sopRequest(`${SOP_PREFIX}/folders/${folderId}`, 'DELETE'),

  getFolderDeletePreview: (folderId: string): Promise<SopDeletePreview> =>
    sopGet(`${SOP_PREFIX}/folders/${folderId}/delete-preview`),

  importSop: async (file: File, folderId?: string): Promise<{ status: string; id: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    if (folderId) {
      formData.append('folder_id', folderId)
    }
    return sopFormRequest(`${SOP_PREFIX}/import`, 'POST', formData)
  },

  parseStepDescription: (description: string): Promise<{
    tool: string
    inputs: Record<string, string>
    outputs: Record<string, string>
  }> => sopRequest(`${SOP_PREFIX}/steps/parse`, 'POST', { description }),

  listKnowledgeNodes: (libraryId: string = 'default'): Promise<KnowledgeNodeItem[]> =>
    sopGet(`${KNOWLEDGE_PREFIX}/nodes?library_id=${libraryId}`),

  getStructuredIndex: (
    docId: string,
    strategy: string = 'doc_blocks_graph_v1',
    keyword?: string,
  ): Promise<{ items: StructuredIndexItem[] }> => {
    let url = `${KNOWLEDGE_PREFIX}/structured/${docId}?strategy=${strategy}`
    if (keyword) url += `&keyword=${encodeURIComponent(keyword)}`
    return sopGet(url)
  },

  searchKnowledgeReferences: (payload: InlineCitationSearchPayload): Promise<any> =>
    sopRequest(`${KNOWLEDGE_PREFIX}/references/search`, 'POST', payload),

  generateSopsFromDoc: async (libraryId: string, docId: string): Promise<{ generated: string[]; total: number }> => {
    try {
      return await sopRequest(`${SOP_PREFIX}/generate-from-doc`, 'POST', { library_id: libraryId, doc_id: docId })
    } catch (err: any) {
      const apiError: ApiErrorDetail | undefined = err?.apiError
      if (apiError?.status === 412) {
        const detail = (apiError.detail ?? {}) as { message?: string; error?: string }
        throw new Error(detail.message || '图谱未就绪，请先在知识图谱模块跑 AI 深度提取')
      }
      throw err
    }
  },

  listDocsWithGraph: (libraryId: string = 'default'): Promise<Array<{ library_id: string; doc_id: string; name: string; relation_count: number }>> =>
    sopGet(`/graph/docs-with-graph?library_id=${libraryId}`),
}
