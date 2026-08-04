"""jsonl → canonical 重建子包（05 第一步：graph 适配 + canonical 组装 + 表格/标签规则）。"""

from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
    CanonicalSourceInput,
    build_canonical_document,
    build_canonical_document_from_blocks,
)
from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import (
    adapt_graph_node,
    adapt_graph_nodes,
    rebuild_canonical_document,
    rebuild_canonical_document_from_graph,
)
from docs_core.step05_sqlite_fts.rebuild.table_semantics import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
    enrich_canonical_table,
)
from docs_core.step05_sqlite_fts.rebuild.tag_rules import (
    infer_conditions,
    infer_entity_tags,
)

__all__ = [
    "CanonicalSourceInput",
    "TABLE_TYPE_HYBRID",
    "TABLE_TYPE_MAPPING_ENUM",
    "TABLE_TYPE_NUMERIC_DENSE",
    "TABLE_TYPE_TEXT_DENSE",
    "adapt_graph_node",
    "adapt_graph_nodes",
    "build_canonical_document",
    "build_canonical_document_from_blocks",
    "enrich_canonical_table",
    "infer_conditions",
    "infer_entity_tags",
    "rebuild_canonical_document",
    "rebuild_canonical_document_from_graph",
]
