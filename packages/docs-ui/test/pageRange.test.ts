import { test } from 'node:test'
import assert from 'node:assert/strict'

import { clampPageToRange, computeSeededPageHeights, normalizePageRange } from '../src/utils/pageRange.ts'

test('normalizePageRange undefined/空数组返回整篇', () => {
  assert.deepEqual(normalizePageRange(undefined, 5), [1, 2, 3, 4, 5])
  assert.deepEqual(normalizePageRange([], 5), [1, 2, 3, 4, 5])
})

test('normalizePageRange 去重、排序、过滤越界与非数字', () => {
  assert.deepEqual(normalizePageRange([7, 3, 3, 0, -1, 100], 5), [3])
})

test('normalizePageRange 全部越界退化为整篇', () => {
  assert.deepEqual(normalizePageRange([0, 99], 4), [1, 2, 3, 4])
})

test('clampPageToRange 边界与就近吸附', () => {
  const range = [3, 4, 7]
  assert.equal(clampPageToRange(1, range), 3)
  assert.equal(clampPageToRange(9, range), 7)
  assert.equal(clampPageToRange(4, range), 4)
  assert.equal(clampPageToRange(5, range), 4)
  assert.equal(clampPageToRange(6, range), 7)
})

test('clampPageToRange 距离相等取较小页', () => {
  assert.equal(clampPageToRange(4, [3, 5]), 3)
})

test('computeSeededPageHeights 均匀页高按比例换算', () => {
  const { pageHeights, estimated } = computeSeededPageHeights([842, 842, 842], 0.85)
  assert.deepEqual(pageHeights, { 1: 728, 2: 728, 3: 728 })
  assert.equal(estimated, 728)
})

test('computeSeededPageHeights 混合页高逐页保留真实尺寸', () => {
  const { pageHeights, estimated } = computeSeededPageHeights([842, 595], 1)
  assert.deepEqual(pageHeights, { 1: 854, 2: 607 })
  assert.equal(estimated, 731)
})

test('computeSeededPageHeights 空输入返回空', () => {
  const result = computeSeededPageHeights([], 1)
  assert.deepEqual(result.pageHeights, {})
  assert.equal(result.estimated, 0)
})

test('clampPageToRange 空数组返回 1', () => {
  assert.equal(clampPageToRange(4, []), 1)
})
