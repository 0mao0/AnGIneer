import type { SmartTreeNode, SOPTreeNode } from '../types'
import type { OpenResourcePayload, ResourceNode } from '../types/resource'

export interface ProjectItem {
  id: string
  name: string
  path: string
}

export interface SopItem {
  id: string
  title: string
  description?: string
}

export const createResourceNodeFromKnowledge = (
  node: Pick<SmartTreeNode, 'key' | 'title' | 'isFolder' | 'parentId' | 'filePath' | 'status' | 'visible'>,
  libraryId: string = 'default'
): ResourceNode => {
  return {
    id: node.key,
    title: node.title,
    resourceType: 'knowledge',
    isFolder: node.isFolder,
    libraryId,
    docId: node.key,
    metadata: {
      parentId: node.parentId,
      filePath: node.filePath,
      status: node.status,
      visible: node.visible
    }
  }
}

export const createResourceNodeFromProject = (project: ProjectItem): ResourceNode => {
  return {
    id: project.id,
    title: project.name,
    resourceType: 'project',
    path: project.path
  }
}

type SopResourceLike = SopItem | Pick<SOPTreeNode, 'key' | 'title' | 'description'>

export const createResourceNodeFromSop = (sop: SopResourceLike): ResourceNode => {
  const sopId = 'id' in sop ? sop.id : sop.key

  return {
    id: sopId,
    title: sop.title,
    resourceType: 'sop',
    description: sop.description
  }
}

export const createOpenResourcePayload = (resource: ResourceNode): OpenResourcePayload | null => {
  if (resource.resourceType === 'knowledge' && !resource.isFolder) {
    return {
      key: `knowledge:${resource.libraryId || 'default'}:${resource.docId || resource.id}`,
      type: 'document',
      title: resource.title,
      props: {
        libraryId: resource.libraryId || 'default',
        docId: resource.docId || resource.id,
        title: resource.title
      }
    }
  }

  if (resource.resourceType === 'sop') {
    return {
      key: `sop:${resource.id}`,
      type: 'sop',
      title: resource.title,
      props: {
        sopId: resource.id,
        title: resource.title,
        description: resource.description || ''
      }
    }
  }

  if (resource.resourceType === 'project') {
    return {
      key: `project:${resource.id}`,
      type: 'project',
      title: resource.title,
      props: {
        projectId: resource.id,
        projectName: resource.title,
        path: resource.path || ''
      }
    }
  }

  return null
}
