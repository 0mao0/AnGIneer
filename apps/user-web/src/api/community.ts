/** 公开测试集 / 公开 SOP 两页的后端调用（/api/community，契约=设计 §10）。
 *  走 aichatApiClient：baseURL /api、自动带 Bearer（登录投稿归属用）、cookie 随同源请求带上。 */
import { aichatApiClient } from '../../../shared/apiClient'

export type CommunityScope = 'eval' | 'sop'
export type ItemOrigin = 'official' | 'user'

export interface TreeItem {
  item_id: string
  origin: ItemOrigin
  ref_id: string
  node_id: string
  kind: string // dataset | sop
  title: string
  subtitle: string
  question_count: number | null
  created_at: string
  author_label: string
}

export interface TreeNode {
  node_id: string
  parent_id: string | null
  title: string
  sort_order: number
}

export interface TreePayload {
  scope: CommunityScope
  nodes: TreeNode[]
  items: TreeItem[]
}

export interface DatasetCard {
  dataset_id: string
  title: string
  description: string
  question_count: number
  category: string
  version: string
  meta: Record<string, string>
  origin?: ItemOrigin
  author_label?: string
}

export interface PublicQuestion {
  question_id: string
  question: string
  intent_level: string
  origin: ItemOrigin
  tags: string[]
  answer?: string
  created_at?: string
  author_label?: string
}

export interface SopComment {
  comment_id: string
  sop_id: string
  step_ref: string
  comment: string
  author_label: string
  created_at: string
}

export interface SubmitPayload {
  scope: CommunityScope
  kind: 'dataset' | 'question' | 'sop_comment'
  node_id?: string
  parent_ref?: string
  step_ref?: string
  title?: string
  payload: Record<string, unknown>
}

export interface SubmitResult {
  submission_id: string
  status: string
  author_label: string
  created_at: string
}

export const communityApi = {
  getTree: (scope: CommunityScope) =>
    aichatApiClient.get<TreePayload>('/community/tree', { params: { scope } }),
  getDataset: (refId: string, origin: ItemOrigin) =>
    aichatApiClient.get<DatasetCard>(`/community/datasets/${encodeURIComponent(refId)}`, {
      params: { origin },
    }),
  getQuestions: (refId: string, origin: ItemOrigin, offset = 0, limit = 50) =>
    aichatApiClient.get<{ items: PublicQuestion[]; total: number }>(
      `/community/datasets/${encodeURIComponent(refId)}/questions`,
      { params: { origin, offset, limit } },
    ),
  /** SOP 详情是上游全量 JSON，字段随 sop-api 演进，前端只消费已知键 */
  getSop: (sopId: string) =>
    aichatApiClient.get<Record<string, any>>(`/community/sops/${encodeURIComponent(sopId)}`),
  getComments: (sopId: string) =>
    aichatApiClient.get<{ comments: SopComment[] }>(
      `/community/sops/${encodeURIComponent(sopId)}/comments`,
    ),
  submit: (body: SubmitPayload) =>
    aichatApiClient.post<SubmitResult>('/community/submissions', body),
}

/** 后端 400/429 的中文 detail 直接透传给用户；axios 错误取 detail。 */
export function communityApiErrorText(e: unknown): string {
  const detail = (e as any)?.response?.data?.detail || (e as any)?.apiError?.message
  return typeof detail === 'string' && detail.trim() ? detail : '操作失败，请稍后重试。'
}
