import { test } from 'node:test'
import assert from 'node:assert/strict'
import { cloneTree } from '../src/utils/tree.ts'

test('cloneTree：保留非序列化字段（Date/Map）', () => {
  const createdAt = new Date('2026-01-01')
  const tags = new Map([['a', 1]])
  const tree = [{ key: 'x', title: 't', createdAt, tags }]
  const out = cloneTree(tree)
  assert.equal(out[0].createdAt instanceof Date, true)
  assert.equal(out[0].tags instanceof Map, true)
  assert.equal(out[0].createdAt, createdAt)
  assert.equal(out[0].tags, tags)
})

test('cloneTree：深拷贝 children 且不改动源数据', () => {
  const tree = [{ key: 'a', title: 'A', children: [{ key: 'b', title: 'B' }] }]
  const out = cloneTree(tree)
  assert.notEqual(out[0], tree[0])
  assert.notEqual(out[0].children, tree[0].children)
  assert.equal(tree[0].children?.[0].key, 'b')
})
