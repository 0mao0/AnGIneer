import { sharedApiClient } from './apiClient'
import type {
  InlineCitationSearchPayload,
  QueryRequest,
  QueryResponse,
} from '@angineer/ui-kit'

/**
 * AIChat 的默认数据传输层实现（AnGIneer 后端契约）。
 * 之前这份实现硬编码在 ui-kit 内部并反向依赖 apps/shared；
 * 现在挪到应用侧，ui-kit 的 AIChat 只认 AIChatTransport 接口。
 */
export const defaultAIChatTransport = {
  query: (payload: QueryRequest, options?: { signal?: AbortSignal }) =>
    sharedApiClient.post<QueryResponse>('/query', payload, {
      signal: options?.signal,
    }),
  fetchModels: () =>
    sharedApiClient.get<Array<{ name: string; configured: boolean }>>(
      '/llm_configs'
    ),
  searchReferences: (payload: InlineCitationSearchPayload) =>
    sharedApiClient.post<{ items?: Record<string, any>[] }>(
      '/knowledge/references/search',
      payload
    ),
}
