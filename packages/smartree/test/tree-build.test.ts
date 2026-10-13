import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildTreeFromFlat, sortTreeNodes, extractTitleNumber, cleanTitleDisplay } from '../src/utils/tree.ts'

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

test('extractTitleNumber：编号前缀识别', () => {
  assert.equal(extractTitleNumber('1【金融】FinanceBench 150题'), 1)
  assert.equal(extractTitleNumber('8【作答】DuReader-robust-zh'), 8)
  assert.equal(extractTitleNumber('12·GDP 100'), 12)
  assert.equal(extractTitleNumber('3【学术】OpenRAG'), 3)
  assert.equal(extractTitleNumber('【法律】LawBench-500题'), null)
  assert.equal(extractTitleNumber('911 事件始末'), null)
  assert.equal(extractTitleNumber('2026 年报'), null)
  assert.equal(extractTitleNumber('OpenRAG 拒答专项（33 题 10-09 版）'), null)
  assert.equal(extractTitleNumber('５【全域】GDP100'), 5)
})

test('cleanTitleDisplay：只净化「编号+【】前缀」，其余原样', () => {
  assert.equal(cleanTitleDisplay('1【金融】FinanceBench 150题'), 'FinanceBench 150题')
  assert.equal(cleanTitleDisplay('2026 年报'), '2026 年报')
  assert.equal(cleanTitleDisplay('OpenRAG 4.0 解析手册'), 'OpenRAG 4.0 解析手册')
  assert.equal(cleanTitleDisplay('12·GDP100 题'), 'GDP100 题')
})

test('sortTreeNodes：numberedFirst 时编号置前，无编号按拼音兜底', () => {
  const nodes = [
    { key: 'd1', title: '【法律】LawBench-500题', sort_order: 0 },
    { key: 'd2', title: '1【金融】FinanceBench 150题', sort_order: 1 },
    { key: 'd3', title: '8【作答】DuReader-robust-zh 作答集 v2', sort_order: 2 },
    { key: 'd4', title: '3【学术】OpenRAG v4.1_1040 题', sort_order: 5 },
  ]
  assert.deepEqual(
    sortTreeNodes(nodes, { numberedFirst: true }).map((n) => n.key),
    ['d2', 'd4', 'd3', 'd1'],
  )
})

test('sortTreeNodes：默认不开 numberedFirst（维持 sort_order 优先）', () => {
  const nodes = [
    { key: 'd1', title: '【法律】LawBench-500题', sort_order: 0 },
    { key: 'd2', title: '1【金融】FinanceBench 150题', sort_order: 1 },
  ]
  assert.deepEqual(sortTreeNodes(nodes).map((n) => n.key), ['d1', 'd2'])
})
