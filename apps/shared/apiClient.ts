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

export const sharedApiClient: UnwrappedAxiosInstance = createApiClient({ baseURL: '/api' }) as UnwrappedAxiosInstance

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
