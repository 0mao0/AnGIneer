import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  collectDescendantNodeIds,
  collectGroupHighlightIds,
  collectLinkedHighlightIds,
  findSectionRootId,
} from '../src/utils/highlightGroup.ts'
import type { GraphNodeLike, LinkedHighlightLike } from '../src/utils/highlightGroup'

const highlight = (
  id: string,
  itemId: string,
  linkedFormulaItemIds?: string[]
): LinkedHighlightLike => ({
  id,
  itemId,
  ...(linkedFormulaItemIds ? { linkedFormulaItemIds } : {}),
})

test('公式激活时同时返回公式自身与解释段高亮', () => {
  const highlights = [
    highlight('formula-body', 'f1'),
    highlight('formula-number', 'f1'),
    highlight('explain-1', 'e1', ['f1']),
    highlight('explain-2', 'e2', ['f1']),
    highlight('other', 'x1'),
  ]
  const ids = collectLinkedHighlightIds(highlights, 'f1')
  assert.deepEqual(ids.sort(), ['explain-1', 'explain-2', 'formula-body', 'formula-number'].sort())
})

test('普通段落激活只返回自身高亮', () => {
  const highlights = [
    highlight('p1', 'p1'),
    highlight('p2', 'p2', ['f1']),
  ]
  assert.deepEqual(collectLinkedHighlightIds(highlights, 'p1'), ['p1'])
})

test('无激活目标返回空数组', () => {
  assert.deepEqual(collectLinkedHighlightIds([], null), [])
})

test('primaryHighlightId 优先并入结果', () => {
  const highlights = [highlight('a', 'f1'), highlight('b', 'f1')]
  assert.deepEqual(collectLinkedHighlightIds(highlights, 'f1', 'b'), ['b', 'a'])
})

const node = (id: string, blockType: string, parentUid?: string | null): GraphNodeLike => ({
  id,
  block_type: blockType,
  ...(parentUid !== undefined ? { parent_uid: parentUid } : {}),
})

const sectionNodes: GraphNodeLike[] = [
  node('title-2.2', 'title'),
  node('p-2.2.1', 'paragraph', 'title-2.2'),
  node('p-2.2.3', 'paragraph', 'title-2.2'),
  node('table-2.2', 'table', 'p-2.2.3'),
  node('other-title', 'title'),
]

test('findSectionRootId 向上找到最近的标题块', () => {
  assert.equal(findSectionRootId(sectionNodes, 'p-2.2.1'), 'title-2.2')
  assert.equal(findSectionRootId(sectionNodes, 'table-2.2'), 'title-2.2')
  assert.equal(findSectionRootId(sectionNodes, 'title-2.2'), 'title-2.2')
  assert.equal(findSectionRootId(sectionNodes, 'no-such'), null)
})

test('findSectionRootId 取最近标题而非最顶层大章', () => {
  const nestedNodes: GraphNodeLike[] = [
    node('title-2', 'title'),
    node('title-2.2', 'title', 'title-2'),
    node('p-2.2.1', 'paragraph', 'title-2.2'),
  ]
  assert.equal(findSectionRootId(nestedNodes, 'p-2.2.1'), 'title-2.2')
  assert.equal(findSectionRootId(nestedNodes, 'title-2.2'), 'title-2.2')
})

test('collectDescendantNodeIds 收集章节全部后代', () => {
  assert.deepEqual(
    collectDescendantNodeIds(sectionNodes, 'title-2.2').sort(),
    ['p-2.2.1', 'p-2.2.3', 'table-2.2'].sort()
  )
  assert.deepEqual(collectDescendantNodeIds(sectionNodes, 'p-2.2.3'), ['table-2.2'])
})

test('普通段落激活时整节一起高亮', () => {
  const highlights = [
    highlight('h-title', 'title-2.2'),
    highlight('h-p1', 'p-2.2.1'),
    highlight('h-p3', 'p-2.2.3'),
    highlight('h-table', 'table-2.2'),
  ]
  const ids = collectGroupHighlightIds(highlights, sectionNodes, 'p-2.2.3')
  assert.deepEqual(ids.sort(), ['h-p3', 'h-table', 'h-title', 'h-p1'].sort())
})

test('citation jump with expandSection=false only highlights the target block', () => {
  const highlights = [
    highlight('h-title', 'title-2.2'),
    highlight('h-p1', 'p-2.2.1'),
    highlight('h-p3', 'p-2.2.3'),
    highlight('h-table', 'table-2.2'),
  ]
  const ids = collectGroupHighlightIds(highlights, sectionNodes, 'p-2.2.3', null, false)
  assert.deepEqual(ids, ['h-p3'])
})

test('公式激活不展开整节，只带公式自身与解释段', () => {
  const formulaNodes: GraphNodeLike[] = [
    node('title-2.2', 'title'),
    node('f-6.2.8', 'equation_interline', 'title-2.2'),
    node('e1', 'paragraph', 'title-2.2'),
  ]
  const highlights = [
    highlight('h-formula', 'f-6.2.8'),
    highlight('h-number', 'f-6.2.8'),
    highlight('h-e1', 'e1', ['f-6.2.8']),
    highlight('h-title', 'title-2.2'),
  ]
  const ids = collectGroupHighlightIds(highlights, formulaNodes, 'f-6.2.8')
  assert.deepEqual(ids.sort(), ['h-e1', 'h-formula', 'h-number'].sort())
})

test('expandSection=false keeps formula plus its explanation highlights', () => {
  const formulaNodes: GraphNodeLike[] = [
    node('title-2.2', 'title'),
    node('f-6.2.8', 'equation_interline', 'title-2.2'),
    node('e1', 'paragraph', 'title-2.2'),
  ]
  const highlights = [
    highlight('h-formula', 'f-6.2.8'),
    highlight('h-number', 'f-6.2.8'),
    highlight('h-e1', 'e1', ['f-6.2.8']),
    highlight('h-title', 'title-2.2'),
  ]
  const ids = collectGroupHighlightIds(highlights, formulaNodes, 'f-6.2.8', null, false)
  assert.deepEqual(ids.sort(), ['h-e1', 'h-formula', 'h-number'].sort())
})
