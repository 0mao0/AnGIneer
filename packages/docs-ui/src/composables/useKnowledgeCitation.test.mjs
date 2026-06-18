import assert from 'node:assert/strict'
import test from 'node:test'
import { ref } from 'vue'

import { useKnowledgeCitation } from './useKnowledgeCitation.ts'

/** 构造用于引用定位测试的最小工作区依赖。 */
function createWorkspaceContext() {
  const selectedNode = ref(null)
  const graphData = ref({
    nodes: [{
      id: 'target-1',
      block_uid: 'target-1',
      page_idx: 4,
      title_path: '第一章/示例小节',
      plain_text: '新协议片段正文'
    }],
    edges: []
  })
  const calls = []
  return {
    selectedNode,
    graphData,
    calls,
    workspaceRef: {
      setActiveLinkedItem(targetId, options) {
        calls.push({ targetId, options })
      }
    },
    onLoadNodes: async (key) => {
      selectedNode.value = key ? { key } : null
    },
    onLoadDocContent: async () => undefined,
    onLoadStructuredStats: async () => undefined,
    onLoadStructuredIndex: async () => undefined,
    keepCurrentPreview: () => false
  }
}

test('focusCitationInWorkspace 支持 reference 协议引用定位', async () => {
  const { focusCitationInWorkspace } = useKnowledgeCitation()
  const context = createWorkspaceContext()

  await focusCitationInWorkspace(
    {
      label: '示例引用',
      reference: {
        targetId: 'target-1',
        targetType: 'content',
        docId: 'doc-1',
        docTitle: '示例文档',
        pageIdx: 5,
        sectionPath: '第一章/示例小节',
        snippet: '新协议片段正文'
      },
      score: 0.91
    },
    context.selectedNode,
    context.graphData,
    context.onLoadNodes,
    context.onLoadDocContent,
    context.onLoadStructuredStats,
    context.onLoadStructuredIndex,
    context.workspaceRef,
    context.keepCurrentPreview
  )

  assert.equal(context.calls.length, 1)
  assert.equal(context.calls[0]?.targetId, 'target-1')
  assert.equal(context.calls[0]?.options.preferredPage, 5)
  assert.equal(context.selectedNode.value?.key, 'doc-1')
})

test('focusCitationInWorkspace 继续兼容旧扁平 citation 字段', async () => {
  const { focusCitationInWorkspace } = useKnowledgeCitation()
  const context = createWorkspaceContext()

  await focusCitationInWorkspace(
    {
      target_id: 'target-1',
      target_type: 'content',
      doc_id: 'doc-legacy',
      doc_title: '旧协议文档',
      page_idx: 5,
      section_path: '第一章/示例小节',
      snippet: '新协议片段正文',
      score: 0.88
    },
    context.selectedNode,
    context.graphData,
    context.onLoadNodes,
    context.onLoadDocContent,
    context.onLoadStructuredStats,
    context.onLoadStructuredIndex,
    context.workspaceRef,
    context.keepCurrentPreview
  )

  assert.equal(context.calls.length, 1)
  assert.equal(context.calls[0]?.targetId, 'target-1')
  assert.equal(context.calls[0]?.options.preferredPage, 5)
  assert.equal(context.selectedNode.value?.key, 'doc-legacy')
})
