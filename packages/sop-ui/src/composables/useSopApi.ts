/**
 * SOP API 封装，提供 SOP 和文件夹的 CRUD 操作，以及知识库搜索。
 */
import type { SopData, SopFolder, SopListItem } from '../types/sop'

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

/** SOP API 方法集合 */
export const sopApi = {
  /** 获取 SOP 列表 */
  listSops: (): Promise<{ sops: SopListItem[] }> => sopGet(API_PREFIX),

  /** 获取单个 SOP 完整内容 */
  getSop: (id: string): Promise<SopData> => sopGet(`${API_PREFIX}/${id}`),

  /** 创建新 SOP */
  createSop: (data: Partial<SopData> & { name_zh: string }): Promise<{ status: string; id: string }> =>
    sopRequest(API_PREFIX, 'POST', data),

  /** 更新 SOP */
  saveSop: (id: string, data: Partial<SopData>): Promise<{ status: string; id: string }> =>
    sopRequest(`${API_PREFIX}/${id}`, 'PUT', data),

  /** 删除 SOP */
  deleteSop: (id: string): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/${id}`, 'DELETE'),

  /** 获取文件夹列表 */
  getFolders: (): Promise<{ folders: SopFolder[] }> => sopGet(`${API_PREFIX}/folders/list`),

  /** 创建文件夹 */
  createFolder: (data: { title: string; parent_folder_id?: string }): Promise<{ status: string; folder_id: string }> =>
    sopRequest(`${API_PREFIX}/folders`, 'POST', data),

  /** 更新文件夹 */
  updateFolder: (folderId: string, data: { title?: string; parent_folder_id?: string }): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/folders/${folderId}`, 'PATCH', data),

  /** 删除文件夹 */
  deleteFolder: (folderId: string): Promise<{ status: string }> =>
    sopRequest(`${API_PREFIX}/folders/${folderId}`, 'DELETE'),

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
}
