export type ResourceType = 'project' | 'knowledge' | 'sop'

export type WorkbenchTabType = 'document' | 'sop' | 'gis' | 'code' | 'project'

export interface ResourceNode {
  id: string
  title: string
  resourceType: ResourceType
  isFolder?: boolean
  description?: string
  libraryId?: string
  docId?: string
  path?: string
  metadata?: Record<string, unknown>
}

export interface OpenResourcePayload {
  key: string
  type: WorkbenchTabType
  title: string
  props: Record<string, unknown>
}
