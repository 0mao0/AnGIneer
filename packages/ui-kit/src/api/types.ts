import type {
  InlineCitationSearchPayload,
  QueryRequest,
  QueryResponse,
} from '../types'

/**
 * AIChat 的数据传输层契约。
 * 组件只依赖这个接口，具体实现（axios/fetch/后端地址）由宿主项目注入，
 * 这样 AIChat 本体可以无改动移植到任意 Vue3 项目。
 */
export interface AIChatTransport {
  /** 发送问答请求（流式/非流式均可，返回完整响应） */
  query: (
    payload: QueryRequest,
    options?: {
      signal?: AbortSignal
      /** 流式增量回调：transport 内部逐块收到回答时调用 */
      onDelta?: (delta: string) => void
    }
  ) => Promise<QueryResponse>
  /** 获取可用模型列表（可选） */
  fetchModels?: () => Promise<Array<{ name: string; configured: boolean }>>
  /** 内联引用搜索（可选，未配置时组件退化为不可用并给出提示） */
  searchReferences?: (
    payload: InlineCitationSearchPayload
  ) => Promise<{ items?: Record<string, any>[] }>
}
