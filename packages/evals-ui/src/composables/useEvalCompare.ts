/** 评测对比 composable。 */
import { ref } from 'vue'
import type { EvalCompareResult } from '../types/eval'

/** 将 query 参数编码为 URL 安全的值。 */
function encodeQueryValue(value: string): string {
  return encodeURIComponent(value)
}

export function useEvalCompare() {
  const compareResult = ref<EvalCompareResult | null>(null)
  const loading = ref(false)

  const compare = async (runIdA: string, runIdB: string) => {
    loading.value = true
    try {
      const resp = await fetch(
        `/api/evals/compare?run_id_a=${encodeQueryValue(runIdA)}&run_id_b=${encodeQueryValue(runIdB)}`
      )
      if (resp.ok) {
        compareResult.value = await resp.json()
      }
    } finally {
      loading.value = false
    }
  }

  const clear = () => {
    compareResult.value = null
  }

  return {
    compareResult,
    loading,
    compare,
    clear,
  }
}
