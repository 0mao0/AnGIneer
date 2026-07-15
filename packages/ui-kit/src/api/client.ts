import { sharedApiClient } from '../../../../apps/shared/createApiClient'
import type { AxiosRequestConfig } from 'axios'

interface ApiPostOptions {
  signal?: AbortSignal
}

async function apiGet<T = any>(url: string): Promise<T> {
  return sharedApiClient.get<T>(url)
}

async function apiPost<T = any>(url: string, body: any, options?: ApiPostOptions): Promise<T> {
  const config: AxiosRequestConfig = { signal: options?.signal }
  return sharedApiClient.post<T>(url, body, config)
}

export const llmApi = {
  getConfigs: () => apiGet<any[]>('/llm_configs'),
}

export const queryApi = {
  query: (payload: any, options?: ApiPostOptions) => apiPost<any>('/query', payload, options),
}

export const referenceApi = {
  search: (payload: any, options?: ApiPostOptions) => apiPost<any>('/knowledge/references/search', payload, options),
}

export const apiClient = { get: apiGet, post: apiPost }
