/** API 客户端共享配置与拦截器注册 */
export interface ApiClientConfig {
  baseURL: string
  timeout?: number
}

/** 默认超时时间（毫秒） */
export const DEFAULT_API_TIMEOUT = 30000

/** 注册统一的响应拦截器：自动解包 response.data */
export const registerDataUnwrapInterceptor = (instance: any) => {
  instance.interceptors.response.use(
    (response: any) => response.data,
    (error: any) => Promise.reject(error)
  )
  return instance
}

/** 生成标准化的 API 客户端配置 */
export const getApiClientConfig = (options: ApiClientConfig) => ({
  baseURL: options.baseURL,
  timeout: options.timeout ?? DEFAULT_API_TIMEOUT
})
