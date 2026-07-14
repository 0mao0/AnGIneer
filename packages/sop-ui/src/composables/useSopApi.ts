/**
 * SOP API 封装，提供 SOP 和文件夹的 CRUD 操作，以及知识库搜索。
 */
import type { InlineCitationSearchPayload } from '@angineer/ui-kit'
import type { RawSopData, SopData, SopFolder, SopListItem } from '../types/sop'
import { normalizeSopData, serializeSopData } from '../types/sop'

const API_PREFIX = '/api/sops'
const KNOWLEDGE_PREFIX = '/api/knowledge'

/** 通用 GET 请求 */
async function sopGet<T = any>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`SOP API GET ${url} failed: ${response.status}`)
  }
  return response.json()
}

/** 通用 POST/PUT/PATCH/DELETE 请求 */
async function sopRequest<T = any>(url: string, method: string, body?: any): Promise<T> {
  const options: RequestInit = {
    method,
    headers: { 'Content-Type': 'application/json' },
  }
  if (body !== undefined) {
    options.body = JSON.stringify(body)
  }
  const response = await fetch(url, options)
  if (!response.ok) {
    const errText = await response.text().catch(() => '')
    throw new Error(errText || `SOP API ${method} ${url} failed: ${response.status}`)
  }
  return response.json()
}

/** 通用 FormData 请求 */
async function sopFormRequest<T = any>(url: string, method: string, body: FormData): Promise<T> {
  const response = await fetch(url, {
    method,
    body,
  })
  if (!response.ok) {
    const errText = await response.text().catch(() => '')
    throw new Error(errText || `SOP API ${method} ${url} failed: ${response.status}`)
  }
  return response.json()
}

/** 知识库文档节点（list_nodes 返回的扁平项） */
interface KnowledgeNodeItem {
  id: string
  title: string
  type: string
  parent_id?: string | null
  file_path?: string
  strategy?: string
}

/** 结构化索引条目 */
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

/** SOP API 方法集合 */
export const sopApi = {
  /** 获取 SOP 列表 */
  listSops: (): Promise<{ sops: SopListItem[] }> => sopGet(API_PREFIX),

  /** 获取单个 SOP 完整内容 */
  getSop: async (id: string): Promise<SopData> => {
    const data = await sopGet<RawSopData>(`${API_PREFIX}/${id}`)
    return normalizeSopData(data)
  },

  /** 创建新 SOP */
  createSop: (data: Partial<SopData> & { name_zh: string }): Promise<{ status: string; id: string }> =>
    sopRequest(API_PREFIX, 'POST', data),

  /** 更新 SOP */
  saveSop: (id: string, data: Partial<SopData>): Promise<{ status: string; id: string }> => {
    const payload = data.steps ? serializeSopData(data as SopData) : data
    return sopRequest(`${API_PREFIX}/${id}`, 'PUT', payload)
  },

  /** 更新 SOP 元数据。 */
  updateSopMeta: (
    id: string,
    data: Partial<Pick<SopData, 'name_zh' | 'name_en' | 'description' | 'folder_id' | 'sort_order'>>
  ): Promise<{ status: string; id: string }> => sopRequest(`${API_PREFIX}/${id}`, 'PUT', data),

  /** 删除 SOP */
  deleteSop: (id: string): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/${id}`, 'DELETE'),

  /** 获取 SOP 删除影响预览。 */
  getSopDeletePreview: (id: string): Promise<SopDeletePreview> =>
    sopGet(`${API_PREFIX}/${id}/delete-preview`),

  /** 获取文件夹列表 */
  getFolders: (): Promise<{ folders: SopFolder[] }> => sopGet(`${API_PREFIX}/folders/list`),

  /** 创建文件夹 */
  createFolder: (data: { title: string; parent_folder_id?: string | null; sort_order?: number }): Promise<{ status: string; folder_id: string }> =>
    sopRequest(`${API_PREFIX}/folders`, 'POST', data),

  /** 更新文件夹 */
  updateFolder: (folderId: string, data: { title?: string; parent_folder_id?: string | null; sort_order?: number }): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/folders/${folderId}`, 'PATCH', data),

  /** 删除文件夹 */
  deleteFolder: (folderId: string): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/folders/${folderId}`, 'DELETE'),

  /** 获取文件夹删除影响预览。 */
  getFolderDeletePreview: (folderId: string): Promise<SopDeletePreview> =>
    sopGet(`${API_PREFIX}/folders/${folderId}/delete-preview`),

  /** 通过 Markdown 文件导入 SOP。 */
  importSop: async (file: File, folderId?: string): Promise<{ status: string; id: string }> => {
    const formData = new FormData()
    formData.append('file', file)
    if (folderId) {
      formData.append('folder_id', folderId)
    }
    return sopFormRequest(`${API_PREFIX}/import`, 'POST', formData)
  },

  /** 解析步骤描述中的工具、输入与输出。 */
  parseStepDescription: (description: string): Promise<{
    tool: string
    inputs: Record<string, string>
    outputs: Record<string, string>
  }> => sopRequest(`${API_PREFIX}/steps/parse`, 'POST', { description }),

  /** 获取知识库文档节点列表 */
  listKnowledgeNodes: (libraryId: string = 'default'): Promise<KnowledgeNodeItem[]> =>
    sopGet(`${KNOWLEDGE_PREFIX}/nodes?library_id=${libraryId}`),

  /** 获取文档的结构化索引条目 */
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

  /** 从文档图谱一键生成 SOP 列表（图谱未就绪时返回 412） */
  generateSopsFromDoc: async (libraryId: string, docId: string): Promise<{ generated: string[]; total: number }> => {
    try {
      return await sopRequest(`/api/sops/generate-from-doc`, 'POST', { library_id: libraryId, doc_id: docId })
    } catch (err: any) {
      if (err?.response?.status === 412) {
        const detail = err.response.data?.detail || {}
        throw new Error(detail.message || '图谱未就绪，请先在知识图谱模块跑 AI 深度提取')
      }
      throw err
    }
  },

  /** 获取有图谱数据的文档列表 */
  listDocsWithGraph: (libraryId: string = 'default'): Promise<Array<{ library_id: string; doc_id: string; name: string; relation_count: number }>> =>
    sopGet(`/api/graph/docs-with-graph?library_id=${libraryId}`),
}
