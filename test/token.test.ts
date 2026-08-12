import { test } from 'node:test'
import assert from 'node:assert/strict'

import { formatTokenCount } from '../src/utils/token.ts'

test('千以内直接显示整数', () => {
  assert.equal(formatTokenCount(0), '0')
  assert.equal(formatTokenCount(999), '999')
})

test('千以上用 k，最多一位小数并去掉末尾的 .0', () => {
  assert.equal(formatTokenCount(1000), '1k')
  assert.equal(formatTokenCount(1234), '1.2k')
  assert.equal(formatTokenCount(1999), '2k')
})

test('万以上用 w', () => {
  assert.equal(formatTokenCount(10_000), '1w')
  assert.equal(formatTokenCount(12_345), '1.2w')
  assert.equal(formatTokenCount(999_999), '100w')
})

test('百万以上用 m', () => {
  assert.equal(formatTokenCount(1_000_000), '1m')
  assert.equal(formatTokenCount(1_234_567), '1.2m')
  assert.equal(formatTokenCount(12_000_000), '12m')
})
