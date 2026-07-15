import axios, { type AxiosInstance, type AxiosRequestConfig } from 'axios'
import { type ApiErrorDetail } from './types'

export interface CreateApiClientOptions {
  baseURL?: string
  timeout?: number
  getAuthToken?: () => string | null
}

export function normalizeApiError(err: unknown): ApiErrorDetail {
  if (!axios.isAxiosError(err)) {
    return {
      status: 0,
      message: err instanceof Error ? err.message : String(err),
      raw: err,
    }
  }
  const status = err.response?.status ?? 0
  const detail = err.response?.data?.detail
  const message =
    (typeof detail === 'object' && detail !== null && 'message' in detail
      ? String((detail as { message: unknown }).message)
      : undefined) ||
    err.message ||
    err.statusText ||
    `API 请求失败（${status}）`
  return { status, detail, message, raw: err }
}

export function createApiClient(options: CreateApiClientOptions = {}): AxiosInstance {
  const baseURL = options.baseURL ?? '/api'
  const timeout = options.timeout ?? 30000
  const instance = axios.create({ baseURL, timeout })

  instance.interceptors.request.use((config) => {
    if (options.getAuthToken) {
      const token = options.getAuthToken()
      if (token) {
        config.headers = config.headers ?? {}
        config.headers.Authorization = `Bearer ${token}`
      }
    }
    return config
  })

  instance.interceptors.response.use(
    (response) => response.data,
    (error) => {
      const normalized = normalizeApiError(error)
      const wrapped = new Error(normalized.message) as Error & { apiError: ApiErrorDetail }
      wrapped.apiError = normalized
      return Promise.reject(wrapped)
    }
  )

  return instance
}

export const FORM_DATA_CONFIG: AxiosRequestConfig = {
  headers: { 'Content-Type': 'multipart/form-data' },
}
