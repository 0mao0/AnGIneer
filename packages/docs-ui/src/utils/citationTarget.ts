/**
 * 归一化引用 target id：去掉 chunk/table/title 聚合前缀与行/摘要后缀，
 * 映射到 doc_blocks_graph 里的真实节点 id。
 *
 * 例：
 * - table-doc-7544e99e:9:10            -> doc-7544e99e:9:10
 * - chunk-doc-7544e99e:9:11            -> doc-7544e99e:9:11
 * - chunk-title-doc-7544e99e:9:7       -> doc-7544e99e:9:7
 * - chunk-table-doc-7544e99e:9:10-summary -> doc-7544e99e:9:10
 * - chunk-table-doc-7544e99e:9:10-row-0   -> doc-7544e99e:9:10
 */
export const normalizeCitationTargetId = (targetId: string): string => {
  let id = String(targetId || '').trim()
  id = id.replace(/-(?:row|summary)(?:-\d+)?$/, '')
  id = id.replace(/^(?:chunk-)?(?:table|title)-/, '')
  id = id.replace(/^chunk-/, '')
  return id
}
