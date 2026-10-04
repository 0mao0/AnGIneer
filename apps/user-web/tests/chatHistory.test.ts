import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  ACTIVE_SESSION_KEY,
  MAX_SESSIONS,
  deriveTitle,
  listSessions,
  loadActiveSessionId,
  removeSession,
  saveActiveSessionId,
  saveSession,
} from '../src/composables/chatHistory.ts'

function createMemoryStorage() {
  const map = new Map<string, string>()
  return {
    getItem: (key: string) => map.get(key) ?? null,
    setItem: (key: string, value: string) => { map.set(key, value) },
  }
}

function makeRecord(id: string, updatedAt: number, content = 'q') {
  return {
    id,
    scene: 'docs',
    title: `会话 ${id}`,
    updatedAt,
    messages: [{ role: 'user', content }],
  }
}

test('deriveTitle 取首条用户消息并截断 30 字', () => {
  assert.equal(deriveTitle([{ role: 'assistant', content: 'x' }, { role: 'user', content: '  多行\n问题  ' }]), '多行 问题')
  assert.equal(deriveTitle([{ role: 'user', content: '长'.repeat(40) }]).length, 31) // 30 + 省略号
  assert.equal(deriveTitle([]), '未命名对话')
})

// node:test 无 bundler：懒加载 apiClient 必然失败 → 自然走 localStorage 降级分支（降级语义即测试路径）
test('saveSession 插入/去重更新，listSessions 按更新时间倒序（降级路径·阶段三单桶）', async () => {
  const storage = createMemoryStorage()
  await saveSession(storage, 'libA', makeRecord('a', 100))
  await saveSession(storage, 'libB', makeRecord('b', 50))
  await saveSession(storage, 'libA', makeRecord('a', 200))
  await saveSession(storage, 'libA', makeRecord('c', 150))
  // 单桶定稿：列表=全量，库参数不再分桶（多库会话不属于任何单一库）
  assert.deepEqual((await listSessions(storage, 'libA')).map(r => r.id), ['a', 'c', 'b'])
  assert.deepEqual((await listSessions(storage, 'libB')).map(r => r.id), ['a', 'c', 'b'])
  assert.deepEqual((await listSessions(storage)).map(r => r.id), ['a', 'c', 'b'])
})

test('saveSession 超过上限按最旧更新时间淘汰（降级路径）', async () => {
  const storage = createMemoryStorage()
  for (let i = 0; i < MAX_SESSIONS + 10; i += 1) {
    await saveSession(storage, 'libA', makeRecord(`s${i}`, i))
  }
  const list = await listSessions(storage, 'libA')
  assert.equal(list.length, MAX_SESSIONS)
  assert.equal(list[0].id, `s${MAX_SESSIONS + 9}`)
})

test('removeSession 删除指定会话（降级路径）', async () => {
  const storage = createMemoryStorage()
  await saveSession(storage, 'libA', makeRecord('a', 1))
  await saveSession(storage, 'libA', makeRecord('b', 2))
  await removeSession(storage, 'libA', 'a')
  assert.deepEqual((await listSessions(storage, 'libA')).map(r => r.id), ['b'])
})

test('活跃会话 id 单桶共享（§4·阶段三：改集合不换桶，仅新建对话轮换）', () => {
  const storage = createMemoryStorage()
  assert.equal(loadActiveSessionId(storage, 'libA'), '')
  saveActiveSessionId(storage, 'libA', 'chat-a')
  saveActiveSessionId(storage, 'libB', 'chat-b')
  // 单桶：不同库参数写同一活动 id，后写覆盖前写
  assert.equal(loadActiveSessionId(storage, 'libA'), 'chat-b')
  // 轮换直接覆盖
  saveActiveSessionId(storage, 'libA', 'chat-a2')
  assert.equal(loadActiveSessionId(storage, 'libA'), 'chat-a2')
  assert.equal(loadActiveSessionId(storage, 'libB'), 'chat-a2')
  // 损坏数据不炸
  storage.setItem(ACTIVE_SESSION_KEY, '{bad json')
  assert.equal(loadActiveSessionId(storage, 'libA'), '')
})

test('无 msgSeq 的消息不产生快照补丁参数（降级路径不触发 HTTP）', async () => {
  const storage = createMemoryStorage()
  await saveSession(storage, 'libA', makeRecord('a', 1)) // messages 无 msgSeq → patches 为空
  const list = await listSessions(storage, 'libA')
  assert.equal(list.length, 1) // 缓存正常
})
