/** 评测运行管理 composable。 */
import { ref } from 'vue'
import type { EvalRun, EvalRunDetail } from '../types/eval'

export function useEvalRun() {
  const currentRun = ref<EvalRun | null>(null)
  const lastRun = ref<EvalRun | null>(null)
  const runs = ref<EvalRun[]>([])
  const loading = ref(false)
  const runDetails = ref<Map<string, EvalRunDetail>>(new Map())
  const evaluatingQuestionIds = ref<Set<string>>(new Set())
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

  /** 获取最近一次已完成的运行记录 */
  const fetchLastRun = async (datasetId: string) => {
    await fetchRuns(datasetId)
    const completedRuns = runs.value.filter(r => r.status === 'completed')
    if (completedRuns.length > 0) {
      const latest = completedRuns.reduce((a, b) =>
        new Date(a.completed_at || a.started_at) > new Date(b.completed_at || b.started_at) ? a : b
      )
      const resp = await fetch(`/api/evals/runs/${latest.run_id}`)
      if (resp.ok) {
        lastRun.value = await resp.json()
        if (lastRun.value?.details) {
          const map = new Map<string, EvalRunDetail>()
          for (const d of lastRun.value.details) {
            map.set(d.question_id, d)
          }
          runDetails.value = map
        }
      }
    } else {
      lastRun.value = null
    }
  }

  /** 对单道题目发起评测，复用整体评测接口 */
  const evaluateQuestion = async (datasetId: string, questionId: string) => {
    evaluatingQuestionIds.value = new Set(evaluatingQuestionIds.value).add(questionId)
    try {
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ dataset_id: datasetId, question_id: questionId }),
      })
      if (!resp.ok) {
        const errText = await resp.text().catch(() => '')
        throw new Error(errText || `评测失败 (${resp.status})`)
      }
      const { run_id } = await resp.json()
      await new Promise<void>((resolve, reject) => {
        const poll = async () => {
          try {
            const r = await fetch(`/api/evals/runs/${run_id}`)
            if (!r.ok) return
            const run: EvalRun = await r.json()
            if (run.status === 'completed' || run.status === 'failed') {
              const detail = run.details?.find(d => d.question_id === questionId)
              if (detail) {
                const map = new Map(runDetails.value)
                map.set(questionId, detail)
                runDetails.value = map
              }
              resolve()
              return
            }
          } catch {
            // 轮询失败继续重试
          }
          setTimeout(poll, 1000)
        }
        poll()
      })
    } finally {
      const next = new Set(evaluatingQuestionIds.value)
      next.delete(questionId)
      evaluatingQuestionIds.value = next
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
    lastRun,
    runs,
    loading,
    runDetails,
    evaluatingQuestionIds,
    startRun,
    fetchRun,
    fetchRuns,
    fetchLastRun,
    evaluateQuestion,
    startPolling,
    stopPolling,
  }
}
