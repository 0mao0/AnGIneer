/**
 * 聊天历史持久化（服务端 HTTP 实现，计划 §5 步 5）。
 * 接口形状（listSessions/saveSession/removeSession）保持原注释承诺不变、改 async：
 * 服务端 chat.sqlite 为真相源（跨设备可见），localStorage 降级为缓存（HTTP 失败时兜底）。
 *
 * 三个语义：
 * - listSessions：HTTP 列表；成功时镜像 localStorage 缓存 + 按 id 差集补录存量（幂等）；
 * - saveSession：localStorage 缓存同步写 + HTTP 展示字段快照补丁（D8/D10：只补带
 *   服务端 msgSeq 的消息、只写 citations/thinking_trace 等展示字段，role/content 服务端权威）；
 * - removeSession：localStorage 同步删 + HTTP 删除（best-effort）。
 *
 * apiClient 走懒加载动态导入：node:test 等无 bundler 环境 import 失败时自然落入
 * localStorage 降级分支（这正是降级语义的测试路径），vite 下静态路径解析不受影响。
 */
import type { UnwrappedAxiosInstance } from '../../../shared/apiClient'

async function api(): Promise<UnwrappedAxiosInstance> {
  const mod = await import('../../../shared/apiClient')
  return mod.aichatApiClient
}

export interface ChatSessionRecord {
  id: string
  scene: string
  title: string
  updatedAt: number
  messages: unknown[]
  /** 服务端列表返回的消息条数（抽屉展示用；缓存降级时缺省走 messages.length） */
  messageCount?: number
}

type StorageLike = Pick<Storage, 'getItem' | 'setItem'>

export const CHAT_HISTORY_STORAGE_KEY = 'ag_chat_history_v1'
export const MAX_SESSIONS_PER_LIBRARY = 50

/** 活跃会话 id 按库持久化（§4）：挂载复用、仅「新建对话/换库」轮换 */
export const ACTIVE_SESSION_KEY = 'ag_active_session_v1'
const IMPORTED_KEY = 'ag_chat_imported_v1'

// ---------------------------------------------------------------- localStorage 缓存层

function readAll(storage: StorageLike): Record<string, ChatSessionRecord[]> {
  try {
    const raw = storage.getItem(CHAT_HISTORY_STORAGE_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw)
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) return {}
    return parsed as Record<string, ChatSessionRecord[]>
  } catch {
    return {}
  }
}

function writeAll(storage: StorageLike, data: Record<string, ChatSessionRecord[]>): void {
  try {
    storage.setItem(CHAT_HISTORY_STORAGE_KEY, JSON.stringify(data))
  } catch (error) {
    // 配额超限或隐私模式：跳过本次持久化，不影响会话本身
    console.warn('[chatHistory] 写入聊天历史失败，已跳过本次:', error)
  }
}

function readImportedIds(storage: StorageLike): Set<string> {
  try {
    const raw = storage.getItem(IMPORTED_KEY)
    const parsed = raw ? JSON.parse(raw) : []
    return new Set(Array.isArray(parsed) ? parsed : [])
  } catch {
    return new Set()
  }
}

function markImported(storage: StorageLike, ids: string[]): void {
  try {
    const merged = new Set([...readImportedIds(storage), ...ids])
    storage.setItem(IMPORTED_KEY, JSON.stringify([...merged]))
  } catch {
    // 标记失败不阻断，最坏情况是下次 list 重试导入（服务端幂等）
  }
}

/** 会话标题：首条非空用户消息压缩空白后截断 30 字 */
export function deriveTitle(messages: Array<{ role?: string; content?: unknown }>): string {
  const firstUser = messages.find(m => m.role === 'user' && String(m.content ?? '').trim())
  const text = String(firstUser?.content ?? '').trim().replace(/\s+/g, ' ')
  if (!text) return '未命名对话'
  return text.length > 30 ? `${text.slice(0, 30)}…` : text
}

/** 指定库的会话列表（更新时间倒序）；损坏条目被丢弃并顺带写回清理（缓存层） */
function listSessionsLocal(storage: StorageLike, libraryId: string): ChatSessionRecord[] {
  const all = readAll(storage)
  const list = Array.isArray(all[libraryId]) ? all[libraryId] : []
  const valid = list.filter(record =>
    record && typeof record === 'object' &&
    typeof record.id === 'string' &&
    Array.isArray(record.messages)
  )
  if (valid.length !== list.length) {
    all[libraryId] = valid
    writeAll(storage, all)
  }
  return [...valid].sort((a, b) => b.updatedAt - a.updatedAt)
}

function saveSessionLocal(storage: StorageLike, libraryId: string, record: ChatSessionRecord): void {
  const all = readAll(storage)
  const list = Array.isArray(all[libraryId]) ? all[libraryId] : []
  const next = [...list.filter(item => item?.id !== record.id), record]
    .sort((a, b) => b.updatedAt - a.updatedAt)
    .slice(0, MAX_SESSIONS_PER_LIBRARY)
  all[libraryId] = next
  writeAll(storage, all)
}

function removeSessionLocal(storage: StorageLike, libraryId: string, sessionId: string): void {
  const all = readAll(storage)
  const list = Array.isArray(all[libraryId]) ? all[libraryId] : []
  all[libraryId] = list.filter(item => item?.id !== sessionId)
  writeAll(storage, all)
}

// ---------------------------------------------------------------- HTTP 真相源

/** 会话列表：HTTP 优先，失败降级 localStorage 缓存 */
export async function listSessions(storage: StorageLike, libraryId: string): Promise<ChatSessionRecord[]> {
  try {
    const data = await (await api()).get<{ sessions?: Array<Record<string, any>> }>(
      '/chat/sessions',
      { params: { library_id: libraryId } }
    )
    const records: ChatSessionRecord[] = (data.sessions || []).map(s => ({
      id: String(s.id),
      scene: String(s.scene || 'qa'),
      title: String(s.title || '未命名对话'),
      updatedAt: Number(s.updatedAt) || 0,
      messages: [],
      messageCount: Number(s.messageCount ?? 0),
    }))
    // 缓存镜像：保留本地消息数组（HTTP 详情失败时 restore 可用）
    const local = listSessionsLocal(storage, libraryId)
    const localById = new Map(local.map(r => [r.id, r]))
    const merged = records.map(r => {
      const cached = localById.get(r.id)
      return cached ? { ...r, messages: cached.messages } : r
    })
    const all = readAll(storage)
    all[libraryId] = merged.slice(0, MAX_SESSIONS_PER_LIBRARY)
    writeAll(storage, all)
    void importMissingSessions(storage, libraryId, merged)
    return merged
  } catch {
    return listSessionsLocal(storage, libraryId)
  }
}

/** 存量导入（§4）：按 id 差集把 localStorage 有而服务端没有的会话补录，幂等 */
async function importMissingSessions(
  storage: StorageLike,
  libraryId: string,
  serverRecords: ChatSessionRecord[]
): Promise<void> {
  const serverIds = new Set(serverRecords.map(r => r.id))
  const imported = readImportedIds(storage)
  const candidates = listSessionsLocal(storage, libraryId).filter(
    r => !serverIds.has(r.id) && !imported.has(r.id) && r.messages.length
  )
  const done: string[] = []
  for (const record of candidates) {
    try {
      const resp = await (await api()).post<{ imported?: number; already_exists?: boolean }>(
        '/chat/sessions/import',
        {
          session_id: record.id,
          scene: record.scene || 'qa',
          library_id: libraryId,
          messages: (record.messages as Array<{ role?: string }>).filter(
            m => m && (m.role === 'user' || m.role === 'assistant')
          ),
        }
      )
      if (resp?.already_exists || (resp?.imported ?? 0) >= 0) done.push(record.id)
    } catch {
      // 单条失败不阻断其余；未标记 → 下次 list 重试（服务端幂等）
    }
  }
  if (done.length) markImported(storage, done)
}

/** 消息全集（恢复会话用）：服务端详情，失败抛错由调用方降级缓存 */
export async function fetchSessionMessages(sessionId: string): Promise<Array<Record<string, any>>> {
  const data = await (await api()).get<{ messages?: Array<Record<string, any>> }>(
    `/chat/sessions/${encodeURIComponent(sessionId)}`
  )
  return (data.messages || [])
    .filter(m => m.role === 'user' || m.role === 'assistant')
    .map(m => {
      const { msgSeq, role, content, ...meta } = m
      return { id: `seq-${msgSeq}`, role, content, msgSeq, ...meta }
    })
}

/** 展示字段快照补丁：只写带服务端 msgSeq 的消息、只补展示字段（D8/D10） */
export async function saveSession(storage: StorageLike, libraryId: string, record: ChatSessionRecord): Promise<void> {
  saveSessionLocal(storage, libraryId, record)
  const patches = (record.messages as Array<Record<string, any>>)
    .filter(m => m && typeof m.msgSeq === 'number')
    .map(m => {
      const metaPatch: Record<string, unknown> = {}
      if (Array.isArray(m.citations) && m.citations.length) metaPatch.citations = m.citations
      if (Array.isArray(m.thinking_trace) && m.thinking_trace.length) metaPatch.thinking_trace = m.thinking_trace
      if (m.strategy) metaPatch.strategy = m.strategy
      return Object.keys(metaPatch).length ? { msg_seq: m.msgSeq, meta_patch: metaPatch } : null
    })
    .filter((p): p is { msg_seq: number; meta_patch: Record<string, unknown> } => p !== null)
  if (!patches.length) return
  try {
    await (await api()).put(`/chat/sessions/${encodeURIComponent(record.id)}/messages`, { patches })
  } catch (error) {
    // 快照补丁失败不阻断会话（服务端 role/content 已权威落库，展示字段下次会话内变更再补）
    console.warn('[chatHistory] 展示字段快照补丁失败:', error)
  }
}

/** 删除指定库中指定 id 的会话（HTTP + 缓存同步删） */
export async function removeSession(storage: StorageLike, libraryId: string, sessionId: string): Promise<void> {
  removeSessionLocal(storage, libraryId, sessionId)
  try {
    await (await api()).delete(`/chat/sessions/${encodeURIComponent(sessionId)}`)
  } catch (error) {
    console.warn('[chatHistory] 删除会话失败:', error)
  }
}

// ---------------------------------------------------------------- 活跃会话 id（§4）

export function loadActiveSessionId(storage: StorageLike, libraryId: string): string {
  try {
    const raw = storage.getItem(ACTIVE_SESSION_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    const id = parsed?.[libraryId]
    return typeof id === 'string' && id ? id : ''
  } catch {
    return ''
  }
}

export function saveActiveSessionId(storage: StorageLike, libraryId: string, sessionId: string): void {
  try {
    const raw = storage.getItem(ACTIVE_SESSION_KEY)
    const parsed = raw ? JSON.parse(raw) : {}
    parsed[libraryId] = sessionId
    storage.setItem(ACTIVE_SESSION_KEY, JSON.stringify(parsed))
  } catch {
    // 活跃 id 丢失的最坏结果 = 新建会话，不阻断
  }
}
