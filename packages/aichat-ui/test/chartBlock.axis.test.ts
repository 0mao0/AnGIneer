/** chartBlock 量级差双 y 轴：多系列 bar/line 数值量级差大时第二系列挂右轴
 *  （std-water 实测：总长 110m 与总宽 16.3m 挤同轴，窄量系列被压扁）。 */
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { needsSecondaryAxis } from '../src/utils/chartBlock.ts'

test('量级差 ≥5 倍触发双轴（实测场景：总长110 vs 总宽16.3）', () => {
  const series = [
    { name: '总长(m)', data: [56, 75, 110] },
    { name: '总宽(m)', data: [11, 13.8, 16.3] },
  ]
  assert.equal(needsSecondaryAxis(series), true)
})

test('量级接近不触发（2 倍内）', () => {
  const series = [
    { name: '2022', data: [3592, 13127] },
    { name: '2021', data: [3056, 9680] },
  ]
  assert.equal(needsSecondaryAxis(series), false)
})

test('单系列不触发', () => {
  assert.equal(needsSecondaryAxis([{ name: 'A', data: [1, 2, 3000] }]), false)
})

test('空数据/坏数据不抛异常', () => {
  assert.equal(needsSecondaryAxis([]), false)
  assert.equal(needsSecondaryAxis([{ name: 'A' }, { name: 'B' }]), false)
  assert.equal(needsSecondaryAxis([{ name: 'A', data: [] }, { name: 'B', data: [1] }]), false)
})

test('全零/负值安全（不除零）', () => {
  assert.equal(needsSecondaryAxis([{ name: 'A', data: [0, 0] }, { name: 'B', data: [0, 0] }]), false)
  assert.equal(needsSecondaryAxis([{ name: 'A', data: [-5, -1] }, { name: 'B', data: [-1, -2] }]), false)
})

// buildOption 分配逻辑（SSR 实测抓过「只判大 5 倍、小量级漏挂」的反向漏判）：
import { secondaryAxisIndexes } from '../src/utils/chartBlock.ts'

test('分配：大基准在前，小量级后续挂右轴（总长110 vs 总宽16.3）', () => {
  const series = [
    { name: '总长(m)', data: [56, 110] },
    { name: '总宽(m)', data: [11, 16.3] },
  ]
  assert.deepEqual(secondaryAxisIndexes(series), [1])
})

test('分配：小基准在前，大量级后续同样挂右轴（总宽16.3 vs 总长110）', () => {
  const series = [
    { name: '总宽(m)', data: [11, 16.3] },
    { name: '总长(m)', data: [56, 110] },
  ]
  assert.deepEqual(secondaryAxisIndexes(series), [1])
})

test('分配：量级接近全部左轴', () => {
  const series = [
    { name: '2022', data: [3592, 13127] },
    { name: '2021', data: [3056, 9680] },
  ]
  assert.deepEqual(secondaryAxisIndexes(series), [])
})
