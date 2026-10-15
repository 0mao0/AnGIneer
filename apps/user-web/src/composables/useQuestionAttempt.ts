/** 公开测试集页「答题」尝试状态：每题一条内存态，点「答题」→ 单题评测 run → 轮询 → 终态展示。
 *
 *  业主 2026-10-15：回答=调用 aichat 链路（题目+知识库），结果与判分展示在题目展开区；
 *  「用完就结束了」——本组合式只存内存态（刷新即清），服务端单题 run 不进历史、1 小时自动清理。
 *  同一时刻只跑一题（hasRunning 供按钮禁用）：公开页无占用弹框可交互，限流兜底靠宿主 nginx。
 */
import { computed, onBeforeUnmount, reactive, ref, watch } from 'vue'
import { evalRunApi, type EvalRun, type RunDetail } from '@/api/evalRun'

const POLL_INTERVAL_MS = 2500
// 15 分钟上限：实测网关慢时单题链可达 10 分钟以上（2026-10-15 本地 646s 一题），
// 10 分钟会在链路即将完成时误判超时；服务端 run 不受影响（1 小时自清），放宽只影响等待耐心
const ATTEMPT_TIMEOUT_MS = 15 * 60 * 1000
const MAX_FETCH_FAILURES = 6

export interface AttemptCitation {
  marker: string
  title: string
}

export interface QuestionAttempt {
  status: 'running' | 'done' | 'failed'
  runId: string
  startedAt: number
  elapsedMs: number
  /** 终态：模型回答与判分 */
  answer: string
  citations: AttemptCitation[]
  quality: string
  score: number | null
  reason: string
  judge: string
  latencyMs: number
  error: string
}

function blankAttempt(): QuestionAttempt {
  return {
    status: 'running',
    runId: '',
    startedAt: Date.now(),
    elapsedMs: 0,
    answer: '',
    citations: [],
    quality: '',
    score: null,
    reason: '',
    judge: '',
    latencyMs: 0,
    error: '',
  }
}

function sleep(ms: number) {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

function startErrorText(e: unknown): string {
  const detail = (e as any)?.response?.data?.detail
  if (typeof detail === 'string' && detail.trim()) return detail
  if (detail && typeof detail === 'object' && typeof detail.message === 'string') return detail.message
  const status = (e as any)?.response?.status
  if (status === 409) return '当前有评测占用后端，请稍后再试'
  return '发起作答失败，请稍后重试'
}

function terminalRunText(status: string): string {
  if (status === 'failed') return '作答链路失败（评测运行报错）'
  if (status === 'cancelled') return '作答复用被中止'
  return `作答未完成（运行状态：${status}）`
}

export function useQuestionAttempt() {
  const attempts = reactive<Record<string, QuestionAttempt>>({})
  /** 1 秒心跳：驱动「已 N 秒」显示刷新（仅在有在跑尝试时开表） */
  const tick = ref(0)
  let tickTimer: number | null = null
  let alive = true

  const hasRunning = computed(() =>
    Object.values(attempts).some((a) => a.status === 'running'),
  )

  watch(hasRunning, (running) => {
    if (running && tickTimer === null) {
      tickTimer = window.setInterval(() => {
        tick.value += 1
      }, 1000)
    } else if (!running && tickTimer !== null) {
      window.clearInterval(tickTimer)
      tickTimer = null
    }
  })

  /** 切测试集时清场（题号可能跨集重名，防旧尝试错挂新集） */
  function reset() {
    for (const key of Object.keys(attempts)) delete attempts[key]
  }

  function fail(questionId: string, message: string) {
    const cur = attempts[questionId]
    if (!cur || cur.status !== 'running') return
    cur.status = 'failed'
    cur.error = message
    cur.elapsedMs = Date.now() - cur.startedAt
  }

  function fillDone(questionId: string, detail: RunDetail) {
    const cur = attempts[questionId]
    if (!cur || cur.status !== 'running') return
    cur.status = 'done'
    cur.elapsedMs = Date.now() - cur.startedAt
    cur.answer = String(detail.prediction?.answer || '').trim()
    cur.citations = (detail.prediction?.citations || [])
      .map((c) => ({
        marker: String(c.marker || ''),
        title: String(c.doc_title || c.title || ''),
      }))
      .filter((c) => c.marker || c.title)
    cur.quality = String(detail.quality || '')
    const score = detail.scores?.score
    cur.score = typeof score === 'number' ? score : null
    cur.reason = String(detail.scores?.semantic_reason || '')
    cur.judge = String(detail.scores?.judge_used || '')
    cur.latencyMs = Number(detail.latency_ms || 0)
  }

  async function poll(questionId: string, runId: string) {
    let fetchFailures = 0
    for (;;) {
      await sleep(POLL_INTERVAL_MS)
      if (!alive) return
      const cur = attempts[questionId]
      if (!cur || cur.status !== 'running' || cur.runId !== runId) return
      cur.elapsedMs = Date.now() - cur.startedAt
      if (cur.elapsedMs > ATTEMPT_TIMEOUT_MS) {
        fail(questionId, '作答超时（超过 15 分钟未完成），可稍后重试')
        return
      }
      let run: EvalRun
      try {
        run = await evalRunApi.getRun(runId, true)
        fetchFailures = 0
      } catch {
        fetchFailures += 1
        if (fetchFailures >= MAX_FETCH_FAILURES) {
          fail(questionId, '与评测服务失联，已停止等待')
          return
        }
        continue
      }
      const status = String(run?.status || '')
      if (!status || status === 'running') continue
      if (status !== 'completed') {
        fail(questionId, terminalRunText(status))
        return
      }
      // 终态：light 轮询载荷不含 prediction，这里补取全量详情
      let full: EvalRun
      try {
        full = await evalRunApi.getRun(runId, false)
      } catch {
        fail(questionId, '取作答结果失败，请重试')
        return
      }
      const detail = (full?.details || []).find((d) => d.question_id === questionId)
      if (!detail) {
        fail(questionId, '未取到本题作答结果')
        return
      }
      if (detail.status === 'error') {
        fail(questionId, detail.error || '作答链路失败')
        return
      }
      if (!String(detail.prediction?.answer || '').trim()) {
        fail(questionId, '模型未给出回答')
        return
      }
      fillDone(questionId, detail)
      return
    }
  }

  async function start(datasetId: string, questionId: string) {
    const prev = attempts[questionId]
    if (prev?.status === 'running') return
    if (hasRunning.value) return
    attempts[questionId] = blankAttempt()
    try {
      const run = await evalRunApi.startQuestionRun(datasetId, questionId)
      const cur = attempts[questionId]
      if (!cur || cur.status !== 'running') return
      const runId = String(run?.run_id || '')
      if (!runId) {
        fail(questionId, '评测未返回 run_id')
        return
      }
      cur.runId = runId
      void poll(questionId, runId)
    } catch (e) {
      fail(questionId, startErrorText(e))
    }
  }

  onBeforeUnmount(() => {
    alive = false
    if (tickTimer !== null) {
      window.clearInterval(tickTimer)
      tickTimer = null
    }
  })

  return { attempts, hasRunning, tick, start, reset }
}
