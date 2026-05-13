/** 评测运行管理 composable。 */
import { ref } from 'vue'
import type { EvalRun, EvalRunDetail } from '../types/eval'

/** 将路径参数编码为 URL 安全的 segment，避免中文/空格/斜杠等导致请求路径解析异常。 */
function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

/** 将 query 参数编码为 URL 安全的值。 */
function encodeQueryValue(value: string): string {
  return encodeURIComponent(value)
}

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
    const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}`)
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
      if (currentRun.value?.status === 'completed' || currentRun.value?.status === 'failed' || currentRun.value?.status === 'cancelled') {
        stopPolling()
        if (isFullRun.value) {
          lastRun.value = currentRun.value
        } else {
          for (const d of currentRun.value?.details || []) {
            const next = new Set(evaluatingQuestionIds.value)
            next.delete(d.question_id)
            evaluatingQuestionIds.value = next
          }
        }
      }
    }
  }

  const fetchRuns = async (datasetId?: string) => {
    const url = datasetId
      ? `/api/evals/runs?dataset_id=${encodeQueryValue(datasetId)}`
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
    const finishedRuns = runs.value.filter(r => r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled')
    if (finishedRuns.length > 0) {
      const latest = finishedRuns.reduce((a, b) =>
        new Date(a.completed_at || a.started_at) > new Date(b.completed_at || b.started_at) ? a : b
      )
      const resp = await fetch(`/api/evals/runs/${encodePathSegment(latest.run_id)}`)
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

  /** 对单道题目发起评测，异步执行，通过轮询获取结果 */
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
      const runData = await resp.json()
      if (runData.run_id) {
        startPolling(runData.run_id)
      } else {
        throw new Error('评测未返回 run_id')
      }
    } catch (e) {
      const next = new Set(evaluatingQuestionIds.value)
      next.delete(questionId)
      evaluatingQuestionIds.value = next
      throw e
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

  /** 停止当前评测任务 */
  const stopRun = async (runId: string) => {
    try {
      const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) {
        stopPolling()
        await fetchRun(runId)
        if (isFullRun.value && currentRun.value) {
          lastRun.value = currentRun.value
        }
      } else {
        const errText = await resp.text().catch(() => '')
        throw new Error(errText || '停止失败')
      }
    } catch (e) {
      console.error('停止评测失败:', e)
      throw e
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
    stopRun,
  }
}
