import type {
  ResearchProject,
  ResearchRun,
  ResearchCandidate,
  SopResearchDraft,
  EvalResearchDraft,
} from '@angineer/sop-ui'

const RESEARCH_BASE = '/api/sops/research'

async function researchGet<T>(path: string): Promise<T> {
  const res = await fetch(`${RESEARCH_BASE}${path}`)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  return res.json()
}

async function researchRequest<T>(path: string, method: string, body?: unknown): Promise<T> {
  const res = await fetch(`${RESEARCH_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${method} ${path} failed: ${res.status}`)
  return res.json()
}

export const sopResearchApi = {
  listProjects: () => researchGet<{ projects: ResearchProject[] }>('/projects'),
  createProject: (payload: { title: string; library_id: string; doc_id: string; doc_title?: string }) =>
    researchRequest<{ status: string; project: ResearchProject }>('/projects', 'POST', payload),
  getProject: (projectId: string) => researchGet<{ project: ResearchProject }>(`/projects/${projectId}`),

  listRuns: (projectId?: string) =>
    researchGet<{ runs: Array<{ run: ResearchRun; summary: unknown }> }>(
      `/runs${projectId ? `?project_id=${projectId}` : ''}`,
    ).then((res) => ({ runs: res.runs.map((r) => r.run) })),
  createRun: (payload: { project_id: string; library_id?: string; doc_id?: string }) =>
    researchRequest<{ status: string; run: ResearchRun }>('/runs', 'POST', payload),
  getRun: (runId: string) => researchGet<{ run: ResearchRun }>(`/runs/${runId}`),
  stopRun: (runId: string) => researchRequest<{ status: string }>(`/runs/${runId}/stop`, 'POST'),
  retryRun: (runId: string) => researchRequest<{ status: string; run: ResearchRun }>(`/runs/${runId}/retry`, 'POST'),

  listCandidates: (runId: string) => researchGet<{ candidates: ResearchCandidate[] }>(`/runs/${runId}/candidates`),
  listDrafts: (runId: string) =>
    researchGet<{ sop_drafts: SopResearchDraft[]; eval_drafts: EvalResearchDraft[] }>(`/runs/${runId}/drafts`),
  getDraft: (draftId: string) => researchGet<{ draft: SopResearchDraft; detail: any }>(`/drafts/${draftId}`),
  getEvalDraft: (draftId: string) => researchGet<{ draft: EvalResearchDraft; detail: any }>(`/evals/${draftId}`),

  approveSopDraft: (draftId: string, payload: { reviewer?: string; comment?: string }) =>
    researchRequest<{ status: string; draft_id: string; review_status: string }>(`/drafts/${draftId}/approve-sop`, 'POST', payload),
  rejectSopDraft: (draftId: string, payload: { reviewer?: string; comment?: string }) =>
    researchRequest<{ status: string; draft_id: string; review_status: string }>(`/drafts/${draftId}/reject`, 'POST', payload),
  approveEvalDraft: (draftId: string, payload: { reviewer?: string; comment?: string }) =>
    researchRequest<{ status: string; draft_id: string; review_status: string }>(`/evals/${draftId}/approve-dataset`, 'POST', payload),
  rejectEvalDraft: (draftId: string, payload: { reviewer?: string; comment?: string }) =>
    researchRequest<{ status: string; draft_id: string; review_status: string }>(`/evals/${draftId}/reject`, 'POST', payload),
}
