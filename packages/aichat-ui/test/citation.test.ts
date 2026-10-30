import { test } from 'node:test'
import assert from 'node:assert/strict'

import {
  buildInlineCitationTagHtml,
  citationMentionedInText,
  formatCitationShortLabel,
  getCitationTagLabel,
  getCitationTagTooltip,
  getCitationHoverText,
  parseMarkerNumber,
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

test('内联证据圆圈 HTML：数字圆圈 + hover 原文 + 跳转数据', () => {
  const html = buildInlineCitationTagHtml(
    {
      ...citation,
      doc_title: '推广产品.docx',
      section_path: '产品一："上航数联"',
      snippet: '表 A.0.2-1 杂货船设计船型尺度',
    },
    0,
    10,
  )
  assert.ok(html.includes('class="citation-circle"'))
  assert.ok(html.includes('>10<'))
  assert.ok(html.includes('data-citation-index="0"'))
  assert.ok(html.includes('data-doc-id="doc-1"'))
  assert.ok(html.includes('data-page-idx="0"'))
  assert.ok(html.includes('&quot;'))
  assert.ok(html.includes('title="表 A.0.2-1 杂货船设计船型尺度"'))
  assert.ok(!html.includes('citation-tag-inline'))
})

test('marker 序号解析：[K10] → 10', () => {
  assert.equal(parseMarkerNumber('K10'), 10)
  assert.equal(parseMarkerNumber('T3'), 3)
  assert.equal(parseMarkerNumber(undefined), undefined)
})

test('所有序号统一为 CSS 实心圆，不再叠加 Unicode 圆圈字形', () => {
  const html = buildInlineCitationTagHtml({ ...citation, snippet: 'x' }, 0, 21)
  assert.ok(html.includes('class="citation-circle"'))
  assert.ok(html.includes('>21<'))
  const glyphHtml = buildInlineCitationTagHtml({ ...citation, snippet: 'x' }, 0, 10)
  assert.ok(glyphHtml.includes('class="citation-circle"'))
  assert.ok(glyphHtml.includes('>10<'))
  assert.ok(!glyphHtml.includes('➓'))
})

test('citationMentionedInText 认标准编号（含空格/下划线/斜杠变体）', () => {
  const c = (title: string): BaseChatCitation => ({ target_id: 't', doc_id: 'd', doc_title: title, page_idx: 0, section_path: '', snippet: '' })
  // 正文写 JTS 202-2011，文档名带 .pdf
  assert.equal(citationMentionedInText(c('JTS 202-2011 水运工程混凝土施工规范.pdf'), '根据《JTS 202-2011 水运工程混凝土施工规范》…'), true)
  // 下划线 vs 无分隔：JTG_T 3610-2019 ↔ JTGT 3610-2019
  assert.equal(citationMentionedInText(c('JTG_T 3610-2019 公路路基施工技术规范.pdf'), '按 JTGT 3610-2019 表 4.4.3'), true)
  // 斜杠变体：DB51_T ↔ DB51/T
  assert.equal(citationMentionedInText(c('DB51_T 2244-2016 农村公路路面典型结构设计指南.pdf'), '见 DB51/T 2244-2016 表 5.1.3'), true)
})

test('citationMentionedInText 正文没提到就返回 false（不给错出处）', () => {
  const unrelated: BaseChatCitation = {
    target_id: 't', doc_id: 'd',
    doc_title: 'JTS 195-3-2019 内河电子航道图技术规范.pdf',
    page_idx: 0, section_path: '', snippet: '',
  }
  // 2026-10-30 验收实拍：检索命中无关文档，答案里根本没有这本规范
  assert.equal(citationMentionedInText(unrelated, '水运工程混凝土施工的技术要求主要包括混凝土性能要求…'), false)
  assert.equal(citationMentionedInText(unrelated, ''), false)
})

test('citationMentionedInText 无编号文档按词干匹配，短名不误命中', () => {
  const doc = (title: string): BaseChatCitation => ({ target_id: 't', doc_id: 'd', doc_title: title, page_idx: 0, section_path: '', snippet: '' })
  assert.equal(citationMentionedInText(doc('盐城港大丰港区一期码头工程施工组织设计.pdf'), '参考盐城港大丰港区一期码头工程施工组织设计'), true)
  // 「规范.pdf」这类短名不得命中任意正文
  assert.equal(citationMentionedInText(doc('规范.pdf'), '这里提到了规范两个字'), false)
})
