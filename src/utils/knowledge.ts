import type { SmartTreeNode } from '../types/tree'

export type PreviewFileType = 'pdf' | 'word' | 'markdown' | 'image' | 'text' | 'file'

export const getFileExtension = (path: string): string => {
  if (!path) return ''
  const match = path.match(/\.([a-zA-Z0-9]+)$/)
  return match ? match[1].toLowerCase() : ''
}

export const getPreviewFileType = (node?: Partial<SmartTreeNode> | null): PreviewFileType => {
  const source = node?.filePath || node?.file_path || node?.title || ''
  const ext = String(source).toLowerCase().split('.').pop() || ''
  if (ext === 'pdf') return 'pdf'
  if (ext === 'doc' || ext === 'docx') return 'word'
  if (ext === 'md' || ext === 'markdown') return 'markdown'
  if (['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'svg'].includes(ext)) return 'image'
  if (['txt', 'json', 'xml', 'csv', 'log', 'js', 'ts', 'py', 'java', 'cpp', 'c', 'h', 'html', 'css'].includes(ext)) return 'text'
  return 'file'
}

const stageMap: Record<string, string> = {
  queued: '任务排队中',
  initializing: '正在初始化',
  mineru_processing: 'MinerU 解析中',
  reading_markdown: '读取 Markdown',
  saving_markdown: '保存解析结果',
  completed: '解析完成',
  failed: '解析失败'
}

export const mapParseStageText = (stage?: string, parseError?: string): string => {
  if (parseError) return `解析失败：${parseError}`
  const normalized = stage || 'processing'
  return stageMap[normalized] || normalized
}

export const mapNodeStatusText = (status?: string): string => {
  const statusTextMap: Record<string, string> = {
    pending: '待处理',
    uploading: '上传中',
    processing: '解析中',
    completed: '已完成',
    failed: '解析失败'
  }
  return statusTextMap[status || ''] || '未知'
}
