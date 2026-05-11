/**
 * 统一 API 客户端封装，替代组件内直接使用 fetch。
 * 提供领域 API（llmApi、queryApi）供 ui-kit 内部组件使用。
 */

/** POST 请求可选参数 */
interface ApiPostOptions {
  signal?: AbortSignal
}

/** 通用 GET 请求 */
async function apiGet<T = any>(url: string): Promise<T> {
  const response = await fetch(url)
  if (!response.ok) {
    throw new Error(`API GET ${url} failed: ${response.status}`)
  }
  return response.json()
}

/** 通用 POST 请求，支持 AbortSignal */
async function apiPost<T = any>(url: string, body: any, options?: ApiPostOptions): Promise<T> {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: options?.signal,
  })
  if (!response.ok) {
    throw new Error(`API POST ${url} failed: ${response.status}`)
  }
  return response.json()
}

/** LLM 配置 API */
export const llmApi = {
  /** 获取可用模型配置列表 */
  getConfigs: () => apiGet<any[]>('/api/llm_configs'),
}

/** 查询 API */
export const queryApi = {
  /** 发送查询请求 */
  query: (payload: any, options?: ApiPostOptions) => apiPost<any>('/api/query', payload, options),
}

export const apiClient = { get: apiGet, post: apiPost }
