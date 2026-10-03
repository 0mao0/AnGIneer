/** 评测题集管理 composable。 */
import { ref } from 'vue'
import type { EvalDataset, EvalFolder, EvalQuestion } from '../types/eval'

/** 生成唯一 dataset_id */
function generateDatasetId(): string {
  return `ds-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 生成唯一 folder_id */
function generateFolderId(): string {
  return `folder-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`
}

/** 将路径参数编码为 URL 安全的 segment，避免中文/空格/斜杠等导致请求路径解析异常。 */
function encodePathSegment(value: string): string {
  return encodeURIComponent(value)
}

/** 题目列表查询条件（服务端分页 + 跨全量筛选；不传 = 全量返回，保持旧行为） */
export interface EvalQuestionQuery {
  offset?: number
  limit?: number
  level?: string
  status?: string
  quality?: string
  runId?: string
}

export function useEvalDataset() {
  const datasets = ref<EvalDataset[]>([])
  const currentDataset = ref<EvalDataset | null>(null)
  const questions = ref<EvalQuestion[]>([])
  /** 服务端筛选后的总题数（分页器用；全量返回时等于当前条数） */
  const questionsTotal = ref(0)
  const folders = ref<EvalFolder[]>([])
  const loading = ref(false)
  /** 题目列表请求序号：丢弃过期响应（连续切题集时先发的慢响应会覆盖后发的） */
  let fetchQuestionsSeq = 0

  const fetchDatasets = async () => {
    loading.value = true
    try {
      const resp = await fetch('/api/evals/datasets')
      if (resp.ok) {
        const data = await resp.json()
        datasets.value = data.datasets || []
      }
    } finally {
      loading.value = false
    }
  }

  const fetchDataset = async (datasetId: string) => {
    loading.value = true
    try {
      const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`)
      if (resp.ok) {
        currentDataset.value = await resp.json()
      }
    } finally {
      loading.value = false
    }
  }

  /** 题目列表。传 query 时走服务端分页 + 跨全量筛选（层级/状态/质量下沉 SQL WHERE，
   *  status/quality 需带 runId 才生效——服务端要 JOIN 当次运行的明细）。
   *  fields=summary：只取列表 UI 真正渲染的列，八个 gold 列不回传；gold 由 fetchQuestion 按需取。
   *  序号守卫：连续切题集/翻页时，先发的慢响应不许覆盖后发的结果（否则列表与选中题集错位）。 */
  const fetchQuestions = async (datasetId: string, query: EvalQuestionQuery = {}) => {
    const seq = ++fetchQuestionsSeq
    loading.value = true
    try {
      const params = new URLSearchParams({ fields: 'summary' })
      if (query.limit !== undefined) {
        params.set('offset', String(Math.max(0, query.offset ?? 0)))
        params.set('limit', String(query.limit))
      }
      if (query.level) params.set('level', query.level)
      if (query.runId) {
        if (query.status) params.set('status', query.status)
        if (query.quality) params.set('quality', query.quality)
      }
      const resp = await fetch(
        `/api/evals/datasets/${encodePathSegment(datasetId)}/questions?${params.toString()}`
      )
      if (resp.ok) {
        const data = await resp.json()
        if (seq !== fetchQuestionsSeq) return
        questions.value = data.questions || []
        questionsTotal.value = typeof data.total === 'number' ? data.total : questions.value.length
      }
    } finally {
      if (seq === fetchQuestionsSeq) loading.value = false
    }
  }

  /** 取题集全部题目（只服务题集卡的层级分布；分页后当前页算不出分布，点开时才拉）。 */
  const fetchAllQuestions = async (datasetId: string): Promise<EvalQuestion[]> => {
    const resp = await fetch(
      `/api/evals/datasets/${encodePathSegment(datasetId)}/questions?fields=summary`
    )
    if (!resp.ok) return []
    const data = await resp.json()
    return data.questions || []
  }

  /** 取单题完整原文（含 gold），原地合并进当前页。
   *  必须是原地合并、不能换数组引用：列表按数组引用做重置/分页，换引用会让页号乱跳。 */
  const fetchQuestion = async (datasetId: string, questionId: string) => {
    const resp = await fetch(
      `/api/evals/datasets/${encodePathSegment(datasetId)}/questions/${encodePathSegment(questionId)}`
    )
    if (!resp.ok) return null
    const question: EvalQuestion = await resp.json()
    const index = questions.value.findIndex(q => q.question_id === questionId)
    if (index >= 0) Object.assign(questions.value[index], question)
    return question
  }

  const createDataset = async (payload: { title: string; category: string; description?: string }) => {
    const body = { dataset_id: generateDatasetId(), ...payload }
    const resp = await fetch('/api/evals/datasets', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      await fetchDatasets()
      return await resp.json()
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `创建失败 (${resp.status})`)
  }

  const deleteDataset = async (datasetId: string) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除失败 (${resp.status})`)
  }

  const renameDataset = async (datasetId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `重命名失败 (${resp.status})`)
  }

  const fetchFolders = async () => {
    try {
      const resp = await fetch('/api/evals/folders')
      if (resp.ok) {
        const data = await resp.json()
        folders.value = data.folders || []
      }
    } catch {
      folders.value = []
    }
  }

  const createFolder = async (payload: { title: string; category: string; parent_folder_id?: string }) => {
    const folderId = generateFolderId()
    const body = { folder_id: folderId, ...payload }
    const resp = await fetch('/api/evals/folders', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
    if (resp.ok) {
      await fetchFolders()
      return await resp.json()
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `创建文件夹失败 (${resp.status})`)
  }

  const renameFolder = async (folderId: string, newTitle: string) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title: newTitle }),
    })
    if (resp.ok) {
      await fetchFolders()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `重命名文件夹失败 (${resp.status})`)
  }

  const deleteFolder = async (folderId: string) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, { method: 'DELETE' })
    if (resp.ok) {
      await fetchFolders()
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `删除文件夹失败 (${resp.status})`)
  }

  /** 更新文件夹属性（如移动到新父级、更改类别等） */
  const updateFolder = async (folderId: string, updates: Record<string, any>) => {
    const resp = await fetch(`/api/evals/folders/${encodePathSegment(folderId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(updates),
    })
    if (resp.ok) {
      await fetchFolders()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `更新文件夹失败 (${resp.status})`)
  }

  const moveDataset = async (datasetId: string, folderId: string, sortOrder: number = 0) => {
    const resp = await fetch(`/api/evals/datasets/${encodePathSegment(datasetId)}/move`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ folder_id: folderId, sort_order: sortOrder }),
    })
    if (resp.ok) {
      await fetchDatasets()
      return true
    }
    const errText = await resp.text().catch(() => '')
    throw new Error(errText || `移动失败 (${resp.status})`)
  }

  return {
    datasets,
    currentDataset,
    questions,
    questionsTotal,
    folders,
    loading,
    fetchDatasets,
    fetchDataset,
    fetchQuestions,
    fetchQuestion,
    fetchAllQuestions,
    createDataset,
    deleteDataset,
    renameDataset,
    fetchFolders,
    createFolder,
    renameFolder,
    deleteFolder,
    updateFolder,
    moveDataset,
  }
}
