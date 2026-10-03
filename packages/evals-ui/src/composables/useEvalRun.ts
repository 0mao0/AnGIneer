/** 评测运行管理 composable。 */
import { ref } from 'vue'
import type { EvalRun, EvalRunDetail, EvalRunningRun } from '../types/eval'

const EVAL_POLL_INTERVAL_MS = 2000

/** 列表/轮询用的明细投影：只取状态染色列（status/quality/error/latency_ms），
 *  且不回传 1040 份题干（enrich=0）——右栏格子只染色、不显示文字。
 *  scores 实测占 light 载荷 84%，题干约占剩下的大头；展开单题时 fetchQuestionDetail
 *  取回的那份仍带分项分数与全文。 */
const RUN_DETAIL_LIST_FIELDS = 'fields=status&enrich=0'
/** 逐题对比表要题干：显式要富化那份（服务端 enrich=1）。 */
const RUN_DETAIL_ENRICHED_FIELDS = 'fields=status&enrich=1'

export interface EvalRunDetailOptions {
  /** 是否要题干等富化字段（逐题对比用）；默认 false = 右栏染色用的精简版 */
  enrich?: boolean
}

function runDetailFields(opts?: EvalRunDetailOptions): string {
  return opts?.enrich ? RUN_DETAIL_ENRICHED_FIELDS : RUN_DETAIL_LIST_FIELDS
}

function runDetailCacheKey(runId: string, opts?: EvalRunDetailOptions): string {
  return opts?.enrich ? `${runId}|enriched` : runId
}

/** 启动被在跑评测占用（后端 409 eval_busy）：带在跑清单，交给调用方弹框问用户 */
export interface EvalBusyError extends Error {
  code: 'eval_busy'
  running: EvalRunningRun[]
}

/** 判据用 duck-typing 而非 instanceof：跨包/多实例（pnpm 软链 + vite 预构建）下 instanceof 不可靠 */
export function isEvalBusyError(err: unknown): err is EvalBusyError {
  return Boolean(err) && (err as EvalBusyError).code === 'eval_busy'
}

/** 解析启动失败响应体：FastAPI 走 detail，占用时 detail 是 {code, message, running} */
function parseErrorDetail(text: string): unknown {
  try {
    return JSON.parse(text)?.detail ?? text
  } catch {
    return text
  }
}

/** 把 409 eval_busy 还原成带在跑清单的错误；其它形态仍按普通错误可读文案抛出 */
function toStartRunError(detail: unknown, status: number): Error {
  if (detail && typeof detail === 'object' && (detail as { code?: string }).code === 'eval_busy') {
    const busy = new Error((detail as { message?: string }).message || '已有评测正在运行') as EvalBusyError
    busy.code = 'eval_busy'
    busy.running = (detail as { running?: EvalRunningRun[] }).running || []
    return busy
  }
  if (typeof detail === 'string') return new Error(detail || `启动评测失败 (${status})`)
  const message = (detail as { message?: string } | null)?.message
  return new Error(message || `启动评测失败 (${status})`)
}

/** 将路径参数编码为 URL 安全的 segment，避免中文/空格/斜杠等导致请求路径解析异常。 */
function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

/** 将 query 参数编码为 URL 安全的值。 */
function encodeQueryValue(value: string): string {
  return encodeURIComponent(value)
}

/** 合并 prediction 的增量字段，避免轮询中间态抖动导致步骤链闪回。 */
function mergePredictionState(
  existing: Record<string, unknown> | null | undefined,
  incoming: Record<string, unknown> | null | undefined
): Record<string, unknown> | undefined {
  if (!existing && !incoming) return undefined
  if (!existing) return incoming || undefined
  if (!incoming) return existing

  const merged: Record<string, unknown> = { ...existing }
  for (const [key, value] of Object.entries(incoming)) {
    if (value !== undefined) {
      merged[key] = value
    }
  }
  return merged
}

/** 合并题目运行详情，优先保留已到达的 prediction 字段。 */
function mergeRunDetail(
  existing: EvalRunDetail | undefined,
  incoming: EvalRunDetail
): EvalRunDetail {
  if (!existing) return { ...incoming }

  return {
    ...existing,
    ...incoming,
    prediction: mergePredictionState(
      existing.prediction as Record<string, unknown> | null | undefined,
      incoming.prediction as Record<string, unknown> | null | undefined
    ) as EvalRunDetail['prediction'],
  }
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
  /** 按 run 缓存的轻量题目详情（用于面板历史记录/对比） */
  const detailsByRun = ref<Record<string, EvalRunDetail[]>>({})
  /** 进行中的详情拉取，避免同一 run 并发重复请求 */
  const pendingDetails = new Map<string, Promise<EvalRunDetail[]>>()
  let pollTimer: ReturnType<typeof setInterval> | null = null

  /** 启动整体评测。judgeConfigName=新增评测弹框选定的评价模型（判分候选链首位）；
   * restartRunId=「重来」原地重跑（复用同一 run 记录，不新增 item）；
   * allowConcurrent=用户在「已有评测正在运行」弹框里点了确定——跳过占用拦截并发跑 */
  const startRun = async (
    datasetId: string,
    options?: {
      docIds?: string[]
      resumeRunId?: string
      restartRunId?: string
      configName?: string
      judgeConfigName?: string
      allowConcurrent?: boolean
    },
  ) => {
    loading.value = true
    isFullRun.value = true
    try {
      const body: Record<string, any> = { dataset_id: datasetId }
      if (options?.docIds && options.docIds.length > 0) body.doc_ids = options.docIds
      if (options?.resumeRunId) body.resume_run_id = options.resumeRunId
      if (options?.restartRunId) body.restart_run_id = options.restartRunId
      if (options?.configName) body.config_name = options.configName
      if (options?.judgeConfigName) body.judge_config_name = options.judgeConfigName
      if (options?.allowConcurrent) body.allow_concurrent = true
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        // 启动失败必须显式抛出给调用方弹提示——旧实现静默吞掉（如全局评测锁
        // "已有评测任务正在运行"400），用户点了按钮却毫不知情（2026-09-06 实踩）
        const text = await resp.text().catch(() => '')
        // 占用（409 eval_busy）带在跑清单抛给界面，由用户决定要不要并发
        throw toStartRunError(parseErrorDetail(text), resp.status)
      }
      // 新 run 从零开始：清空上一轮的逐题映射与单题评测集合。
      // 不清会导致新 run 轮询合并时残留上一轮的质量标记（跨 run 幽灵数据）。
      runDetails.value = new Map()
      evaluatingQuestionIds.value = new Set()
      currentRun.value = await resp.json()
      runs.value = [currentRun.value!, ...runs.value.filter(r => r.run_id !== currentRun.value!.run_id)]
      startPolling(currentRun.value!.run_id)
    } finally {
      loading.value = false
    }
  }

  /** 整体评测轮询时整体替换 runDetails；单题评测时仅合并对应题目 */
  const fetchRun = async (runId: string) => {
    // 列表投影：不返回 prediction/all_scores/all_predictions 等大字段、也不返回 scores，
    // 轮询只关心进度与逐题状态；展开单题时再按需拉完整详情。
    const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}?${RUN_DETAIL_LIST_FIELDS}`)
    if (resp.ok) {
      currentRun.value = await resp.json()
      // 同步历史列表中的进度字段：标题行（completed_questions/total_questions）
      // 读取的是 runs 列表，若不随轮询更新会出现"标题卡住、明细在动"。
      const updated = currentRun.value
      if (updated) {
        runs.value = runs.value.map(r =>
          r.run_id === runId
            ? {
                ...r,
                status: updated.status ?? r.status,
                completed_questions: updated.completed_questions ?? r.completed_questions,
                total_questions: updated.total_questions ?? r.total_questions,
                summary_scores: updated.summary_scores ?? r.summary_scores,
                completed_at: updated.completed_at ?? r.completed_at,
              }
            : r,
        )
      }
      if (currentRun.value?.details) {
        const map = new Map(runDetails.value)
        if (isFullRun.value) {
          for (const d of currentRun.value.details) {
            map.set(d.question_id, mergeRunDetail(map.get(d.question_id), d))
          }
          runDetails.value = map
        } else {
          for (const d of currentRun.value.details) {
            map.set(d.question_id, mergeRunDetail(map.get(d.question_id), d))
          }
          runDetails.value = map
        }
      }
      if (currentRun.value?.status === 'completed' || currentRun.value?.status === 'failed' || currentRun.value?.status === 'cancelled') {
        stopPolling()
        if (isFullRun.value) {
          lastRun.value = currentRun.value
          // 刷新历史列表：否则 runs 里该条仍是 running/无汇总，
          // 面板会误判"评测中"（停止按钮不消失）、历史项准确率不更新
          void fetchRuns(currentRun.value.dataset_id)
        } else {
          // 单题评测完成：自动拉取该题完整详情，保证展开视图能看到答案/过程
          const runId = currentRun.value.run_id
          for (const d of currentRun.value?.details || []) {
            const next = new Set(evaluatingQuestionIds.value)
            next.delete(d.question_id)
            evaluatingQuestionIds.value = next
            void fetchQuestionDetail(runId, d.question_id)
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

  const deleteRun = async (runId: string, datasetId?: string) => {
    const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}`, { method: 'DELETE' })
    if (!resp.ok) {
      const errText = await resp.text().catch(() => '')
      throw new Error(errText || '删除失败')
    }
    // 如果删除的是当前选中的运行，清除相关状态
    if (lastRun.value?.run_id === runId) {
      lastRun.value = null
      runDetails.value = new Map()
    }
    if (currentRun.value?.run_id === runId) {
      stopPolling()
      currentRun.value = null
    }
    // 刷新运行列表
    const dsId = datasetId || currentRun.value?.dataset_id || lastRun.value?.dataset_id
    await fetchRuns(dsId)
  }

  /** 获取最近一次已完成的运行记录，同时检测运行中任务并恢复轮询 */
  const fetchLastRun = async (datasetId: string) => {
    await fetchRuns(datasetId)

    // 优先检测运行中的任务，恢复轮询
    const runningRun = runs.value.find(r => r.status === 'running')
    if (runningRun) {
      const resp = await fetch(`/api/evals/runs/${encodePathSegment(runningRun.run_id)}?${RUN_DETAIL_LIST_FIELDS}`)
      if (resp.ok) {
        currentRun.value = await resp.json()
        isFullRun.value = runningRun.is_full_run ?? true
        if (currentRun.value?.details) {
          const map = new Map<string, EvalRunDetail>()
          for (const d of currentRun.value.details) {
            map.set(d.question_id, d)
          }
          runDetails.value = map
        }
        startPolling(runningRun.run_id)
      }
    } else if (currentRun.value) {
      // 切到没有运行中任务的数据集：必须清掉上一数据集残留的 currentRun 并停表。
      // 旧实现不清 → 在 A 数据集的评测跑到 B 数据集页面仍显示"停止评测"、
      // 实时面板继续跳数（2026-09-06 实踩）
      stopPolling()
      currentRun.value = null
      runDetails.value = new Map()
    }

    // 加载最近的已完成整体运行作为 lastRun
    const finishedRuns = runs.value.filter(
      r => r.run_id !== runningRun?.run_id &&
        (r.status === 'completed' || r.status === 'failed' || r.status === 'cancelled')
    )
    if (finishedRuns.length > 0) {
      const latest = finishedRuns.reduce((a, b) =>
        new Date(a.completed_at || a.started_at) > new Date(b.completed_at || b.started_at) ? a : b
      )
      // 走 fetchRunDetails：它带 pending 去重 + 结果缓存，右栏 EvalRunPanel 自动选中
      // 同一条 run 时直接命中缓存，不会对同一个 run 再发一次完全相同的请求。
      // 旧实现这里裸 fetch 一次、面板再 fetch 一次——2026-10-03 网关日志实测每次点击题集
      // 都有两条同样的明细请求（1040 题那条 219 KB gzip × 2）。
      const latestDetails = await fetchRunDetails(latest.run_id)
      lastRun.value = { ...latest, details: latestDetails }
      // 如果没有运行中的任务，才从 lastRun 加载 runDetails
      if (!runningRun) {
        if (latestDetails.length) {
          const map = new Map<string, EvalRunDetail>()
          for (const d of latestDetails) {
            map.set(d.question_id, d)
          }
          runDetails.value = map
        } else {
          runDetails.value = new Map()
        }
      }
    } else if (!runningRun) {
      lastRun.value = null
      runDetails.value = new Map()
    }
  }

  /** 加载指定历史运行的完整详情用于展示 */
  const selectHistoricalRun = async (runId: string) => {
    // 复用 runs 列表里的汇总 + fetchRunDetails 的去重/缓存，切换历史记录不再重复请求
    const summary = runs.value.find(r => r.run_id === runId)
    const details = await fetchRunDetails(runId)
    let run: EvalRun
    if (summary) {
      run = { ...summary, details }
    } else {
      const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}?${RUN_DETAIL_LIST_FIELDS}`)
      run = resp.ok ? await resp.json() : {
        run_id: runId,
        dataset_id: '',
        status: 'completed',
        total_questions: details.length,
        completed_questions: details.length,
        started_at: '',
      }
    }
    const runningRun = runs.value.find(r => r.status === 'running')
    if (runningRun?.run_id === runId) {
      // 选中的是正在跑的记录：保持实时轮询，进度半圆/进度条继续更新
      currentRun.value = run
      isFullRun.value = true
      runDetails.value = new Map(details.map(d => [d.question_id, d]))
      startPolling(runId)
      return
    }
    stopPolling()
    lastRun.value = run
    currentRun.value = null
    isFullRun.value = true
    runDetails.value = new Map(details.map(d => [d.question_id, d]))
  }

  /** 按需拉取单道题目的完整运行详情（含 trace 与分项分数），合并进 runDetails */
  const fetchQuestionDetail = async (runId: string, questionId: string) => {
    const resp = await fetch(
      `/api/evals/runs/${encodePathSegment(runId)}/questions/${encodePathSegment(questionId)}`
    )
    if (resp.ok) {
      const detail: EvalRunDetail = await resp.json()
      const map = new Map(runDetails.value)
      map.set(detail.question_id, detail)
      runDetails.value = map
      return detail
    }
    return null
  }

  /** 拉取某次 run 的列表级题目详情（status/quality/error/latency_ms），带缓存；运行中不缓存。
   *  默认精简版（不回题干）；逐题对比等要用题干时传 { enrich: true }（两档各自缓存）。
   *  逐题分项分数两档都不含——展开单题时 fetchQuestionDetail 会取回带 scores 的那一份。 */
  const fetchRunDetails = (
    runId: string,
    opts?: EvalRunDetailOptions,
  ): Promise<EvalRunDetail[]> => {
    const key = runDetailCacheKey(runId, opts)
    const run = currentRun.value?.run_id === runId ? currentRun.value : undefined
    const isRunningRun = run?.status === 'running'
    if (!isRunningRun && detailsByRun.value[key]) {
      return Promise.resolve(detailsByRun.value[key])
    }
    if (pendingDetails.has(key)) {
      return pendingDetails.get(key)!
    }
    const task = (async () => {
      const resp = await fetch(
        `/api/evals/runs/${encodePathSegment(runId)}?${runDetailFields(opts)}`
      )
      if (resp.ok) {
        const data: EvalRun = await resp.json()
        const details = data.details || []
        detailsByRun.value = { ...detailsByRun.value, [key]: details }
        return details
      }
      return []
    })()
    pendingDetails.set(key, task)
    void task.finally(() => pendingDetails.delete(key))
    return task
  }

  /** 清空 run 详情缓存（切换测试集时调用） */
  const clearDetailsCache = () => {
    detailsByRun.value = {}
    pendingDetails.clear()
  }

  /** 对单道题目发起评测，异步执行，通过轮询获取结果。
   * allowConcurrent=用户在占用弹框里点了确定：与在跑的评测并发（与整体评测同一套 409 语义） */
  const evaluateQuestion = async (
    datasetId: string,
    questionId: string,
    docIds?: string[],
    allowConcurrent = false,
  ) => {
    evaluatingQuestionIds.value = new Set(evaluatingQuestionIds.value).add(questionId)
    isFullRun.value = false
    try {
      const body: Record<string, any> = { dataset_id: datasetId, question_id: questionId, save: false }
      if (docIds && docIds.length > 0) body.doc_ids = docIds
      if (allowConcurrent) body.allow_concurrent = true
      const resp = await fetch('/api/evals/runs', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
      if (!resp.ok) {
        const text = await resp.text().catch(() => '')
        throw toStartRunError(parseErrorDetail(text), resp.status)
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
    void fetchRun(runId)
    pollTimer = setInterval(() => fetchRun(runId), EVAL_POLL_INTERVAL_MS)
  }

  const stopPolling = () => {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  /** 停止当前评测任务。优雅停止是异步的（后端完成当前题目才结算 cancelled），
   * 200 只代表"停止指令已受理"：保持轮询直到状态落定（fetchRun 终态自动停表），
   * 立刻停表会让 UI 卡在"运行中"（旧实现实踩）。 */
  const stopRun = async (runId: string) => {
    try {
      const resp = await fetch(`/api/evals/runs/${encodePathSegment(runId)}/stop`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      if (resp.ok) {
        await fetchRun(runId)
        const settled = ['completed', 'failed', 'cancelled'].includes(currentRun.value?.status || '')
        if (settled) {
          stopPolling()
          if (isFullRun.value && currentRun.value) {
            lastRun.value = currentRun.value
          }
        } else {
          // 仍在收尾：继续轮询到终态（startPolling 内部会先清旧表，并立即拉一次）
          startPolling(runId)
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
    fetchQuestionDetail,
    fetchRunDetails,
    clearDetailsCache,
    selectHistoricalRun,
    startPolling,
    stopPolling,
    stopRun,
    deleteRun,
  }
}
