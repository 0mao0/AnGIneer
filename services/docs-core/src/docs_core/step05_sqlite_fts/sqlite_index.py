"""步骤六：从 graph jsonl+meta 重建 canonical 并落 SQLite（canonical 表 + doc_blocks 行 + segments + FTS）。"""

from typing import Any, Dict

import docs_core.paths as paths
from docs_core.step04_structure.shared.jsonl_store import get_doc_blocks_graph
from docs_core.assets_file_store import file_storage as _file_storage
from docs_core.step05_sqlite_fts.store.blocks_sql_store import get_index_store
from docs_core.step05_sqlite_fts.rows_projection import build_doc_block_rows, build_document_segments


def build_sqlite_index_from_graph(
    library_id: str,
    doc_id: str,
    *,
    derive_version: str = "v1",
    parser_version: str = "popo-4b",
) -> Dict[str, Any]:
    """从 doc_blocks_graph.jsonl + meta 重建 canonical SQLite 索引。

    - 标题层级已在 structure 阶段定稿并写入 jsonl，这里不重复调用 LLM
    - 规则类派生字段（entity_tags / conditions / clause_id）由 builder 统一重新推导
    """
    from docs_core.docs_service import docs_service
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document_from_graph

    graph_data = get_doc_blocks_graph(library_id, doc_id)
    if not graph_data:
        raise FileNotFoundError(f"doc_blocks_graph 不存在: {doc_id}（请先运行 structure 阶段）")

    manifest = _file_storage.get_doc_manifest(library_id, doc_id)
    doc_title = str(manifest.get("title") or "") or doc_id

    canonical_document = rebuild_canonical_document_from_graph(
        library_id=library_id,
        doc_id=doc_id,
        graph_data=graph_data,
        title=doc_title,
        use_llm=False,
    )
    docs_service.save_canonical_document_bare(canonical_document)

    index_store = get_index_store()
    base_rows, derived_rows = build_doc_block_rows(
        canonical_document,
        derive_version=derive_version,
        parser_version=parser_version,
    )
    index_store.clear_doc_blocks(doc_id)
    inserted = index_store.insert_doc_blocks_base_rows(base_rows) if base_rows else 0
    updated = index_store.update_doc_blocks_derived_rows(derived_rows) if derived_rows else 0

    node_line_map = {
        str(node.get("block_uid") or node.get("id") or ""): node
        for node in graph_data.get("nodes", [])
    }
    block_line_ranges = []
    for block in canonical_document.blocks:
        node = node_line_map.get(block.block_id, {})
        block_line_ranges.append({
            "block_id": block.block_id,
            "markdown_line_start": node.get("markdown_line_start"),
            "markdown_line_end": node.get("markdown_line_end"),
        })
    segments = build_document_segments(canonical_document, block_line_ranges)
    index_store.clear_document_segments(doc_id)
    saved_segments = index_store.save_document_segments(doc_id, library_id, "doc_blocks_graph_v1", segments)

    docs_service.rebuild_document_fts(doc_id)

    return {
        "canonical_blocks_count": len(canonical_document.blocks),
        "canonical_chunks_count": len(canonical_document.chunks),
        "canonical_tables_count": len(canonical_document.tables),
        "base_rows_count": inserted,
        "derived_rows_count": updated,
        "segments_count": saved_segments,
        "graph_path": str(paths.get_graph_jsonl_path(library_id, doc_id)),
    }


__all__ = ["build_sqlite_index_from_graph"]
