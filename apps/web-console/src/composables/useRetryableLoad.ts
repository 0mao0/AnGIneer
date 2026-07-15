import { ref, shallowRef } from 'vue'
import { message } from 'ant-design-vue'

interface UseRetryableLoadOptions {
  silent?: boolean
  errorMessage?: string
}

interface UseRetryableLoadReturn<T> {
  loading: ReturnType<typeof ref<boolean>>
  error: ReturnType<typeof shallowRef<Error | null>>
  data: ReturnType<typeof shallowRef<T | null>>
  reload: () => Promise<void>
}

export function useRetryableLoad<T>(
  loader: () => Promise<T>,
  options: UseRetryableLoadOptions = {}
): UseRetryableLoadReturn<T> {
  const { silent = false, errorMessage } = options
  const loading = ref(false)
  const error = shallowRef<Error | null>(null)
  const data = shallowRef<T | null>(null)

  const reload = async () => {
    loading.value = true
    error.value = null
    try {
      const result = await loader()
      data.value = result as T
    } catch (err) {
      const e = err instanceof Error ? err : new Error(String(err))
      error.value = e
      if (!silent) {
        message.error(errorMessage || e.message || '加载失败，请稍后重试')
      }
    } finally {
      loading.value = false
    }
  }

  return { loading, error, data, reload }
}
