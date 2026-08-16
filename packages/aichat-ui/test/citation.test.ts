import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInlineCitationTagHtml,
  formatCitationShortLabel,
  getCitationTagLabel,
  getCitationTagTooltip,
  getCitationHoverText,
} from '../src/utils/citation.ts'
import type { BaseChatCitation } from '../src/types/chat'

const citation: BaseChatCitation = {
  target_id: 't1',
  doc_id: 'doc-1',
  doc_title: '推广产品.docx',
  page_idx: 0,
  section_path: '产品一：上航数联（智慧工地底座平台）',
  snippet: '',
  score: 1,
}

test('标签显示《文档名》（去掉扩展名）+ 最后一级章节', () => {
  assert.equal(
    getCitationTagLabel(citation),
    '《推广产品》 · 产品一：上航数联（智慧工地底座平台）'
  )
})

test('无章节时标签只显示《文档名》，且忽略扩展名大小写', () => {
  assert.equal(getCitationTagLabel({ ...citation, section_path: '', doc_title: '推广产品.PDF' }), '《推广产品》')
})

test('悬浮提示展示《文档名》+ 完整章节路径', () => {
  assert.equal(
    getCitationTagTooltip({ ...citation, section_path: '产品总览 > 产品一：上航数联（智慧工地底座平台）' }),
    '《推广产品》 · 产品总览 > 产品一：上航数联（智慧工地底座平台）'
  )
})

test('最终引用标签显示序号+规范名，整体不超过 5 个字', () => {
  assert.equal(formatCitationShortLabel({ ...citation, doc_title: '推广产品.docx' }, 1), '1推广产品')
  assert.equal(formatCitationShortLabel({ ...citation, doc_title: '跨页表格.pdf' }, 2), '2跨页表格')
  assert.equal(formatCitationShortLabel({ ...citation, doc_title: '内河通航标准.pdf' }, 3), '3内河通…')
  assert.equal(formatCitationShortLabel({ ...citation, doc_title: '' }), '未命名')
})

test('最终引用悬浮提示展示引用的文字', () => {
  assert.equal(
    getCitationHoverText({ ...citation, snippet: '表 A.0.2-1 杂货船设计船型尺度' }),
    '表 A.0.2-1 杂货船设计船型尺度'
  )
  assert.equal(
    getCitationHoverText({ ...citation, snippet: '', section_path: '产品一' }),
    '《推广产品》 · 产品一'
  )
})

test('内联出处标签 HTML 携带跳转数据并转义属性', () => {
  const html = buildInlineCitationTagHtml(
    { ...citation, doc_title: '推广产品.docx', section_path: '产品一："上航数联"' },
    0
  )
  assert.ok(html.includes('class="citation-tag-inline"'))
  assert.ok(html.includes('data-citation-index="0"'))
  assert.ok(html.includes('data-doc-id="doc-1"'))
  assert.ok(html.includes('data-page-idx="0"'))
  assert.ok(html.includes('&quot;'))
  assert.ok(html.includes('《推广产品》'))
  assert.ok(!html.includes('推广产品.docx ·'))
})
