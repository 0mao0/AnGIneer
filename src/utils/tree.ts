/** 根据文件名推断图标类型 */
export const getFileIconType = (fileName: string): string => {
  const lowerFileName = fileName.toLowerCase()
  if (lowerFileName.endsWith('.pdf')) return 'pdf'
  if (/\.(doc|docx)$/.test(lowerFileName)) return 'word'
  if (/\.(xls|xlsx|csv)$/.test(lowerFileName)) return 'excel'
  if (/\.(ppt|pptx)$/.test(lowerFileName)) return 'ppt'
  if (/\.(jpg|jpeg|png|gif|webp|svg)$/.test(lowerFileName)) return 'image'
  if (/\.(zip|rar|7z|tar|gz)$/.test(lowerFileName)) return 'zip'
  if (lowerFileName.endsWith('.md')) return 'markdown'
  if (/\.(txt|json|yaml|yml|xml)$/.test(lowerFileName)) return 'text'
  return 'file'
}

/** 生成唯一消息 ID */
export function generateMessageId(): string {
  return `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`
}

/** 估算消息的 token 数量 */
export function estimateTokens(content: string): number {
  if (!content) return 0
  let tokens = 0
  for (const char of content) {
    if (/[\u4e00-\u9fa5]/.test(char)) {
      tokens += 1.5
    } else {
      tokens += 0.5
    }
  }
  return Math.ceil(tokens)
}
