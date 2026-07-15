import type { AxiosInstance } from 'axios'
import { createApiClient } from './createApiClient'

export interface ApiClientConfig {
  baseURL: string
  timeout?: number
}

export const DEFAULT_API_TIMEOUT = 30000

export const sharedApiClient: AxiosInstance = createApiClient({ baseURL: '/api' })

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
