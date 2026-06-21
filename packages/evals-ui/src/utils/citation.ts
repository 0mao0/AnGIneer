export interface EvalCitationItem {
  label?: unknown
  score?: unknown
  fusion_sources?: string[]
  doc_title?: unknown
  doc_id?: unknown
  page_idx?: unknown
  section_path?: unknown
  text?: unknown
  content?: unknown
  snippet?: unknown
  reference?: {
    targetId?: unknown
    targetType?: unknown
    docId?: unknown
    docTitle?: unknown
    pageIdx?: unknown
    sectionPath?: unknown
    snippet?: unknown
    content?: unknown
  } | null
}

export function getCitationEntryLabel(citation: EvalCitationItem | null | undefined): string {
  return String(citation?.label || '').trim()
}

export function getCitationDocTitle(citation: EvalCitationItem | null | undefined): string {
  return String(
    citation?.reference?.docTitle
    || citation?.doc_title
    || citation?.reference?.docId
    || citation?.doc_id
    || ''
  ).trim()
}

export function getCitationPage(citation: EvalCitationItem | null | undefined): number {
  const referencePage = Number(citation?.reference?.pageIdx || 0)
  if (referencePage > 0) return referencePage
  const legacyPage = Number(citation?.page_idx || 0)
  return legacyPage > 0 ? legacyPage : 0
}

export function getCitationSectionPath(citation: EvalCitationItem | null | undefined): string {
  return String(citation?.reference?.sectionPath || citation?.section_path || '').trim()
}

export function getCitationText(citation: EvalCitationItem | null | undefined): string {
  return String(
    citation?.reference?.content
    || citation?.reference?.snippet
    || citation?.content
    || citation?.snippet
    || citation?.text
    || ''
  ).trim()
}
