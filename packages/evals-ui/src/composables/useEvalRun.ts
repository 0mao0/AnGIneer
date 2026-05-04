/** 评测运行管理 composable。 */
import { ref } from 'vue'
import type { EvalRun, EvalRunDetail } from '../types/eval'

export function useEvalRun() {
  const currentRun = ref<EvalRun | null>(null)
  const runs = ref<EvalRun[]>([])
  const loading = ref(false)
  const runDetails = ref<Map<string, EvalRunDetail>>(new Map())
  let pollTimer: ReturnType<typeof setInterval> | null = null

  const startRun = async (datasetId: string) => {
    loading.value = true
    try {
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: datasetId }),
      })
      if (resp.ok) {
        currentRun.value = await resp.json()
        startPolling(currentRun.value!.run_id)
      }
    } finally {
      loading.value = false
    }
  }

  const fetchRun = async (runId: string) => {
    const resp = await fetch(`/api/evals/runs/${runId}`)
    if (resp.ok) {
      currentRun.value = await resp.json()
      if (currentRun.value?.details) {
        const map = new Map<string, EvalRunDetail>()
        for (const d of currentRun.value.details) {
          map.set(d.question_id, d)
        }
        runDetails.value = map
      }
      if (currentRun.value?.status === 'completed' || currentRun.value?.status === 'failed') {
        stopPolling()
      }
    }
  }

  const fetchRuns = async (datasetId?: string) => {
    const url = datasetId
      ? `/api/evals/runs?dataset_id=${datasetId}`
      : '/api/evals/runs'
    const resp = await fetch(url)
    if (resp.ok) {
      const data = await resp.json()
      runs.value = data.runs || []
    }
  }

  const startPolling = (runId: string) => {
    stopPolling()
    pollTimer = setInterval(() => fetchRun(runId), 2000)
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    currentRun,
    runs,
    loading,
    runDetails,
    startRun,
    fetchRun,
    fetchRuns,
    startPolling,
    stopPolling,
  }
}
