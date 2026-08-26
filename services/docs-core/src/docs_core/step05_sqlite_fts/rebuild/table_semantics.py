"""表格语义兼容转发（归位 step04/shared：04 生成、05 透传/兜底）。

实现已迁移到 ``docs_core.step04_structure.shared.table_semantics``，
本模块仅保留原有导入路径，避免 05 重建侧既有引用失效。
"""

from docs_core.step04_structure.shared.table_semantics import (
    TABLE_SEMANTICS_VERSION,
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
    build_table_representations,
    build_table_row_keys,
    build_table_schema,
    build_table_semantics_sidecar,
    build_table_full_text,
    build_text_row_chunks,
    classify_table,
    enrich_canonical_table,
    enrich_graph_nodes_table_semantics,
    extract_table_features,
    is_numeric_like,
    normalize_table_cell,
    parse_table_rows,
    split_header_body,
)

__all__ = [
    "TABLE_SEMANTICS_VERSION",
    "TABLE_TYPE_HYBRID",
    "TABLE_TYPE_MAPPING_ENUM",
    "TABLE_TYPE_NUMERIC_DENSE",
    "TABLE_TYPE_TEXT_DENSE",
    "build_table_representations",
    "build_table_row_keys",
    "build_table_schema",
    "build_table_semantics_sidecar",
    "build_table_full_text",
    "build_text_row_chunks",
    "classify_table",
    "enrich_canonical_table",
    "enrich_graph_nodes_table_semantics",
    "extract_table_features",
    "is_numeric_like",
    "normalize_table_cell",
    "parse_table_rows",
    "split_header_body",
]
