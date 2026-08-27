import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import { createServer } from 'vite'
import vue from '@vitejs/plugin-vue'

const server = await createServer({
  root: fileURLToPath(new URL('../', import.meta.url)),
  plugins: [vue()],
  server: { middlewareMode: true },
  appType: 'custom',
  logLevel: 'silent',
})

try {
  const {
    buildDisplayRoots,
    isFurnitureNode,
  } = await server.ssrLoadModule('/src/utils/knowledge.ts')
  const { buildDocBlocksGraphIndex } = await server.ssrLoadModule('/src/composables/useDocBlocksGraph.ts')

  // 与《海港2》真实解析结果一致的最小复现：
  // 前置页“目录”里同时有内容块和页眉/页码页饰块，且页饰块原本是根节点。
  const graph = {
    nodes: [
      {
        id: 'p0:title',
        block_type: 'title',
        page_idx: 0,
        block_seq: 1,
        plain_text: '目次',
        parent_uid: null,
        document_part: 'front_matter',
        page_role: 'toc',
        layout_category: 'content',
      },
      {
        id: 'p0:body',
        block_type: 'paragraph',
        page_idx: 0,
        block_seq: 2,
        plain_text: '1 总则 …… (1)\n2 术语 …… (2)',
        parent_uid: 'p0:title',
        document_part: 'front_matter',
        page_role: 'toc',
        layout_category: 'content',
      },
      {
        id: 'p0:header',
        block_type: 'page_header',
        page_idx: 0,
        block_seq: 3,
        plain_text: '目次',
        parent_uid: null,
        document_part: 'front_matter',
        page_role: 'page_header',
        layout_category: 'furniture',
      },
      {
        id: 'p0:number',
        block_type: 'page_number',
        page_idx: 0,
        block_seq: 4,
        plain_text: '1',
        parent_uid: null,
        document_part: 'front_matter',
        page_role: 'page_number',
        layout_category: 'furniture',
      },
      {
        id: 'p5:title',
        block_type: 'title',
        page_idx: 5,
        block_seq: 1,
        plain_text: '6 进港航道、锚地及导助航设施',
        parent_uid: null,
        document_part: 'body',
        page_role: 'body',
        layout_category: 'content',
      },
      {
        id: 'p5:header',
        block_type: 'page_header',
        page_idx: 5,
        block_seq: 2,
        plain_text: '海港总体设计规范(JTS 165—2025)',
        parent_uid: null,
        document_part: 'body',
        page_role: 'page_header',
        layout_category: 'furniture',
      },
    ],
    edges: [],
  }

  const { roots, nodeMap, childrenMap } = buildDocBlocksGraphIndex(graph)
  const displayRoots = buildDisplayRoots(roots, nodeMap, childrenMap)

  const expanded = new Set(roots)
  for (const root of displayRoots) {
    if (typeof root !== 'string') expanded.add(root.id)
  }

  const flatIds = []
  const traverse = (ids, depth) => {
    for (const id of ids) {
      const node = nodeMap.get(id)
      if (!node) continue
      flatIds.push(id)
      if (expanded.has(id)) traverse(childrenMap.get(id) || [], depth + 1)
    }
  }
  for (const root of displayRoots) {
    if (typeof root === 'string') {
      traverse([root], 0)
    } else {
      flatIds.push(root.id)
      if (expanded.has(root.id)) traverse(root.children, 1)
    }
  }

  const duplicates = flatIds.filter((id, index) => flatIds.indexOf(id) !== index)
  assert.deepEqual(
    [...new Set(duplicates)],
    [],
    `前置页页饰不应同时出现在顶层根节点和“目录”分组中，实际重复节点：${[...new Set(duplicates)].join(', ')}`,
  )

  for (const root of displayRoots) {
    if (typeof root === 'string') {
      assert.equal(
        isFurnitureNode(nodeMap.get(root)),
        false,
        `页饰节点不应作为顶层根节点出现在树中：${root}`,
      )
    }
  }

  // 没有任何内容块的前置页（无法形成分组）时，页饰仍应保留为顶层根节点，不能因修复而消失。
  const ungroupedGraph = {
    nodes: [
      {
        id: 'p9:header',
        block_type: 'page_header',
        page_idx: 9,
        block_seq: 1,
        plain_text: '孤立页眉',
        parent_uid: null,
        document_part: 'front_matter',
        page_role: 'page_header',
        layout_category: 'furniture',
      },
    ],
    edges: [],
  }
  const ungroupedIndex = buildDocBlocksGraphIndex(ungroupedGraph)
  const ungroupedRoots = buildDisplayRoots(
    ungroupedIndex.roots,
    ungroupedIndex.nodeMap,
    ungroupedIndex.childrenMap,
  )
  assert.ok(
    ungroupedRoots.includes('p9:header'),
    '无内容块前置页的页饰应保留为顶层根节点',
  )
} finally {
  await server.close()
}
