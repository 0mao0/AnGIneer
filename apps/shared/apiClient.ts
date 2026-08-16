import type { AxiosInstance, AxiosRequestConfig } from 'axios'
import { createApiClient } from './createApiClient'

export interface ApiClientConfig {
  baseURL: string
  timeout?: number
}

export const DEFAULT_API_TIMEOUT = 30000

/** Axios 实例，但 .get/.post/.request 等返回原始数据而非 AxiosResponse（由拦截器自动解包） */
export interface UnwrappedAxiosInstance {
  get<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  post<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  put<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  patch<T = any>(url: string, data?: any, config?: AxiosRequestConfig): Promise<T>
  delete<T = any>(url: string, config?: AxiosRequestConfig): Promise<T>
  request<T = any>(config: AxiosRequestConfig): Promise<T>
  interceptors: AxiosInstance['interceptors']
}

/**
 * 租户身份钩子：user-web 登录后把 API key 存入 localStorage('ag_api_key')，
 * 所有 /api 请求自动带 X-API-Key；后端中间件（P1）据此强制库隔离与注入。
 */
function tenantAuthHeaders(): Record<string, string> | null {
  if (typeof localStorage === 'undefined') return null
  const key = localStorage.getItem('ag_api_key')
  return key ? { 'X-API-Key': key } : null
}

export const sharedApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api', getAuthToken: tenantAuthHeaders }) as UnwrappedAxiosInstance

/** 文档处理服务客户端（/api/knowledge、/api/v1、/api/graph、/api/api-keys） */
export const docsApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api', getAuthToken: tenantAuthHeaders }) as UnwrappedAxiosInstance

/** AI 问答服务客户端（/api/chat、/api/sops、/api/evals、/api/dream-cycle、/api/llm_configs） */
export const aichatApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api', timeout: 60000, getAuthToken: tenantAuthHeaders }) as UnwrappedAxiosInstance

export const registerDataUnwrapInterceptor = (instance: AxiosInstance) => {
  instance.interceptors.response.use(
    (response) => response.data,
    (error) => Promise.reject(error)
  )
  return instance
}

export const getApiClientConfig = (options: ApiClientConfig) => ({
  baseURL: options.baseURL,
  timeout: options.timeout ?? DEFAULT_API_TIMEOUT
})
