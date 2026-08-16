import { test } from 'node:test'
import assert from 'node:assert/strict'

import { normalizeCitationTargetId } from '../src/utils/citationTarget.ts'

test('normalizeCitationTargetId 去掉聚合前缀与行/摘要后缀', () => {
  assert.equal(normalizeCitationTargetId('table-doc-7544e99e:9:10'), 'doc-7544e99e:9:10')
  assert.equal(normalizeCitationTargetId('chunk-doc-7544e99e:9:11'), 'doc-7544e99e:9:11')
  assert.equal(normalizeCitationTargetId('chunk-title-doc-7544e99e:9:7'), 'doc-7544e99e:9:7')
  assert.equal(
    normalizeCitationTargetId('chunk-table-doc-7544e99e:9:10-summary'),
    'doc-7544e99e:9:10'
  )
  assert.equal(
    normalizeCitationTargetId('chunk-table-doc-7544e99e:9:10-row-0'),
    'doc-7544e99e:9:10'
  )
  assert.equal(normalizeCitationTargetId('doc-7544e99e:9:7'), 'doc-7544e99e:9:7')
  assert.equal(normalizeCitationTargetId(''), '')
})
