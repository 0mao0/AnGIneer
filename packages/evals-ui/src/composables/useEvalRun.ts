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
  /** 标记当前运行是否为整体评测（区别于单题评测） */
  const isFullRun = ref(false)
  let pollTimer: ReturnType<typeof setInterval> | null = null

  /** 启动整体评测 */
  const startRun = async (datasetId: string, docIds?: string[]) => {
    loading.value = true
    isFullRun.value = true
    try {
      const body: Record<string, any> = { dataset_id: datasetId }
      if (docIds && docIds.length > 0) body.doc_ids = docIds
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (resp.ok) {
        currentRun.value = await resp.json()
        startPolling(currentRun.value!.run_id)
      }
    } finally {
      loading.value = false
    }
  }

  /** 整体评测轮询时整体替换 runDetails；单题评测时仅合并对应题目 */
  const fetchRun = async (runId: string) => {
    const resp = await fetch(`/api/evals/runs/${runId}`)
    if (resp.ok) {
      currentRun.value = await resp.json()
      if (currentRun.value?.details) {
        if (isFullRun.value) {
          const map = new Map<string, EvalRunDetail>()
          for (const d of currentRun.value.details) {
            map.set(d.question_id, d)
          }
          runDetails.value = map
        } else {
          const map = new Map(runDetails.value)
          for (const d of currentRun.value.details) {
            map.set(d.question_id, d)
          }
          runDetails.value = map
        }
      }
      if (currentRun.value?.status === 'completed' || currentRun.value?.status === 'failed') {
        stopPolling()
        if (isFullRun.value) {
          lastRun.value = currentRun.value
        }
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
    const finishedRuns = runs.value.filter(r => r.status === 'completed' || r.status === 'failed')
    if (finishedRuns.length > 0) {
      const latest = finishedRuns.reduce((a, b) =>
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
        } else {
          runDetails.value = new Map()
        }
      } else {
        runDetails.value = new Map()
      }
    } else {
      lastRun.value = null
      runDetails.value = new Map()
    }
  }

  /** 对单道题目发起评测，同步执行，不入库，直接返回结果 */
  const evaluateQuestion = async (datasetId: string, questionId: string, docIds?: string[]) => {
    evaluatingQuestionIds.value = new Set(evaluatingQuestionIds.value).add(questionId)
    isFullRun.value = false
    try {
      const body: Record<string, any> = { dataset_id: datasetId, question_id: questionId, save: false }
      if (docIds && docIds.length > 0) body.doc_ids = docIds
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        const errText = await resp.text().catch(() => '')
        throw new Error(errText || `评测失败 (${resp.status})`)
      }
      const result = await resp.json()
      if (result.details && result.details.length > 0) {
        const detail = result.details[0] as EvalRunDetail
        const map = new Map(runDetails.value)
        map.set(questionId, detail)
        runDetails.value = map
      } else {
        throw new Error('评测未返回结果')
      }
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
    isFullRun,
    startRun,
    fetchRun,
    fetchRuns,
    fetchLastRun,
    evaluateQuestion,
    startPolling,
    stopPolling,
  }
}
