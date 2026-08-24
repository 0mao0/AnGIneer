import { test } from 'node:test'
import assert from 'node:assert/strict'
import { getStatusColor, getStatusText } from '../src/utils/tree.ts'

test('getStatusText：已知状态有中文文案', () => {
  assert.equal(getStatusText('completed'), '已完成')
  assert.equal(getStatusText('failed'), '失败')
})

test('getStatusText：未知状态回退为原值', () => {
  assert.equal(getStatusText('weird'), 'weird')
})

test('getStatusColor：未知状态回退为 default', () => {
  assert.equal(getStatusColor('weird'), 'default')
})
