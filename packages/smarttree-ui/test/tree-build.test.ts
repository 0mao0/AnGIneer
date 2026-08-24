import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildTreeFromFlat, sortTreeNodes } from '../src/utils/tree.ts'

const folders = [
  { key: 'f1', title: 'A 文件夹', isFolder: true, sort_order: 1 },
  { key: 'f2', title: 'B 文件夹', isFolder: true, sort_order: 0 },
  { key: 'f3', title: 'C 子文件夹', isFolder: true, parentId: 'f1', sort_order: 0 },
]

const items = [
  { key: 'i1', title: 'Z 文档', isFolder: false, parentId: 'f1', sort_order: 5 },
  { key: 'i2', title: 'A 文档', isFolder: false, parentId: 'f1', sort_order: 0 },
  { key: 'i3', title: '根文档', isFolder: false, sort_order: 0 },
]

test('buildTreeFromFlat：根级文件夹在前排序，子级正确挂载', () => {
  const tree = buildTreeFromFlat({ folders, items })
  assert.deepEqual(tree.map((n) => n.key), ['f2', 'f1', 'i3'])
  const f1 = tree.find((n) => n.key === 'f1')!
  assert.deepEqual(f1.children?.map((n) => n.key), ['f3', 'i2', 'i1'])
})

test('buildTreeFromFlat：父文件夹未知的节点挂到根级末尾', () => {
  const withOrphan = [...items, { key: 'orphan', title: '孤儿文档', isFolder: false, parentId: 'missing' }]
  const tree = buildTreeFromFlat({ folders, items: withOrphan })
  assert.equal(tree[tree.length - 1].key, 'orphan')
})

test('sortTreeNodes：先按 sort_order，再按中文标题', () => {
  const nodes = [
    { key: 'a', title: '技术方案', sort_order: 2 },
    { key: 'b', title: 'Beta 文档', sort_order: 1 },
    { key: 'c', title: 'Alpha 文档', sort_order: 1 },
  ]
  assert.deepEqual(sortTreeNodes(nodes).map((n) => n.key), ['c', 'b', 'a'])
})

test('sortTreeNodes：foldersFirst 时文件夹在前', () => {
  const nodes = [
    { key: 'f', title: '文件夹', isFolder: true, sort_order: 2 },
    { key: 'd', title: '文档', isFolder: false, sort_order: 1 },
  ]
  assert.deepEqual(sortTreeNodes(nodes, { foldersFirst: true }).map((n) => n.key), ['f', 'd'])
})
