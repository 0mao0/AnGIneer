import { test } from 'node:test'
import assert from 'node:assert/strict'
import { filterTree, getExpandedKeysForSearch } from '../src/utils/tree.ts'

const tree = [
  {
    key: 'a',
    title: '产品文档',
    children: [
      { key: 'a1', title: '需求说明.pdf' },
      { key: 'a2', title: '技术方案.md' },
    ],
  },
  {
    key: 'b',
    title: '项目资料',
    children: [{ key: 'b1', title: '预算表.xlsx' }],
  },
]

test('filterTree：命中子节点时保留祖先', () => {
  const out = filterTree(tree, '预算表')
  assert.equal(out.length, 1)
  assert.equal(out[0].key, 'b')
  assert.equal(out[0].children?.length, 1)
  assert.equal(out[0].children?.[0].key, 'b1')
})

test('filterTree：无命中返回空数组', () => {
  assert.deepEqual(filterTree(tree, '不存在'), [])
})

test('filterTree：关键词需由调用方统一小写', () => {
  const out = filterTree(tree, 'pdf')
  assert.equal(out.length, 1)
  assert.equal(out[0].key, 'a')
})

test('getExpandedKeysForSearch：返回命中路径上的祖先 key', () => {
  assert.deepEqual(getExpandedKeysForSearch(tree, '预算表'), ['b'])
})
