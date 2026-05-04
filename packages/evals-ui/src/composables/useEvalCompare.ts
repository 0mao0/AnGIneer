/** 评测对比 composable。 */
import { ref } from 'vue'
import type { EvalCompareResult } from '../types/eval'

export function useEvalCompare() {
  const compareResult = ref<EvalCompareResult | null>(null)
  const loading = ref(false)

  const compare = async (runIdA: string, runIdB: string) => {
    loading.value = true
    try {
      const resp = await fetch(
        `/api/evals/compare?run_id_a=${runIdA}&run_id_b=${runIdB}`
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
