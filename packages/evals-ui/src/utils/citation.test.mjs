import assert from 'node:assert/strict'
import test from 'node:test'

import {
  getCitationDocTitle,
  getCitationEntryLabel,
  getCitationPage,
  getCitationSectionPath,
  getCitationText,
} from './citation.ts'

test('兼容新协议 citation 字段读取', () => {
  const citation = {
    label: '条目标题',
    reference: {
      docTitle: '示例文档',
      pageIdx: 6,
      sectionPath: '第一章/总则',
      snippet: '这是新协议片段'
    }
  }

  assert.equal(getCitationEntryLabel(citation), '条目标题')
  assert.equal(getCitationDocTitle(citation), '示例文档')
  assert.equal(getCitationPage(citation), 6)
  assert.equal(getCitationSectionPath(citation), '第一章/总则')
  assert.equal(getCitationText(citation), '这是新协议片段')
})

test('继续兼容旧扁平 citation 字段读取', () => {
  const citation = {
    doc_title: '旧协议文档',
    page_idx: 3,
    section_path: '第二章/术语',
    snippet: '这是旧协议片段'
  }

  assert.equal(getCitationEntryLabel(citation), '')
  assert.equal(getCitationDocTitle(citation), '旧协议文档')
  assert.equal(getCitationPage(citation), 3)
  assert.equal(getCitationSectionPath(citation), '第二章/术语')
  assert.equal(getCitationText(citation), '这是旧协议片段')
})

test('正文读取优先使用更完整的 content 字段', () => {
  const citation = {
    content: '旧正文',
    snippet: '旧片段',
    reference: {
      content: '新正文',
      snippet: '新片段'
    }
  }

  assert.equal(getCitationText(citation), '新正文')
})
