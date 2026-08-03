"""统一写入投影（阶段三：写入唯一出口）。

下游产物（content.md / doc_blocks_graph / segments / base_rows+derived_rows）统一从
CanonicalDocument 生成——popo 路径不再经过 popo_projection（阶段三已删除）；
solo 路径的展示投影（graph/segments/富字段）暂由其 write 侧保留，canonical 已通过
G3 适配器直接消费后端块（阶段四）。

- ``build_doc_blocks_graph``：与 popo_projection 的 graph 字段逐项对齐（含
  contd/image/table_merge 三边与 markdown 行号），保证改造前后 popo graph 一致；
- ``build_doc_block_rows``：G4/P11——popo 的 doc_blocks 行补齐 table_html /
  math_content / derived_rows，与 solo 投影对齐。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.ingest.canonical.types import CanonicalBlock, CanonicalDocument


def render_content_md(
    blocks: List[CanonicalBlock],
    build_id: Optional[str] = None,
) -> tuple[str, List[Dict[str, Any]]]:
    """按 (page_idx, reading_order) 渲染 content.md 文本与行号映射。

    返回 (md_text, block_line_ranges)；build_id 写入首行注释（行号偏移已计入）。
    """
    sorted_blocks = sorted(blocks, key=lambda block: (block.page_idx, block.reading_order))
    lines: List[str] = [f"<!-- build_id: {build_id} -->"] if build_id else []
    block_line_ranges: List[Dict[str, Any]] = []
    for block in sorted_blocks:
        text = block.text_clean or block.text
        if not text:
            continue
        block_lines = text.splitlines()
        start_line = len(lines) + 1
        lines.extend(block_lines)
        block_line_ranges.append({
            "block_id": block.block_id,
            "markdown_line_start": start_line,
            "markdown_line_end": len(lines),
        })
    return "\n".join(lines) + ("\n" if lines else ""), block_line_ranges


def _bbox_array(block: CanonicalBlock) -> Optional[List[float]]:
    if not block.bbox:
        return None
    return [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]


def build_doc_blocks_graph(
    document: CanonicalDocument,
    block_line_ranges: List[Dict[str, Any]],
    *,
    generated_by: str = "mineru-popo",
) -> Dict[str, Any]:
    """从 CanonicalDocument 构建 doc_blocks_graph（与 popo_projection 字段对齐）。"""
    line_map = {item["block_id"]: item for item in block_line_ranges}
    nodes: List[Dict[str, Any]] = []
    for block in document.blocks:
        bbox_array = _bbox_array(block)
        nodes.append({
            "id": block.block_id,
            "block_uid": block.block_id,
            "block_type": block.block_type,
            "page_idx": block.page_idx,
            "block_seq": block.reading_order,
            "plain_text": block.text,
            "bbox": bbox_array,
            "bbox_norm_x1": bbox_array[0] if bbox_array else None,
            "bbox_norm_y1": bbox_array[1] if bbox_array else None,
            "bbox_norm_x2": bbox_array[2] if bbox_array else None,
            "bbox_norm_y2": bbox_array[3] if bbox_array else None,
            "derived_level": block.title_level,
            "title_path": block.section_path,
            "parent_uid": block.parent_block_id,
            "markdown_line_start": line_map.get(block.block_id, {}).get("markdown_line_start"),
            "markdown_line_end": line_map.get(block.block_id, {}).get("markdown_line_end"),
            "contd_target_id": block.contd_target_id,
            "image_assoc_id": block.image_assoc_id,
            "table_merge_id": block.table_merge_id,
            "source": generated_by,
        })

    edges: List[Dict[str, Any]] = []
    for block in document.blocks:
        if block.parent_block_id:
            edges.append({
                "id": f"parent-{block.block_id}",
                "from": block.block_id,
                "to": block.parent_block_id,
                "kind": "strong",
                "label": "parent",
            })
        if block.contd_target_id:
            edges.append({
                "id": f"contd-{block.block_id}",
                "from": block.block_id,
                "to": block.contd_target_id,
                "kind": "weak",
                "label": "contd",
            })
        if block.table_merge_id:
            edges.append({
                "id": f"table-merge-{block.block_id}",
                "from": block.block_id,
                "to": block.table_merge_id,
                "kind": "weak",
                "label": "table_merge",
            })

    prev_block: Optional[CanonicalBlock] = None
    for block in sorted(document.blocks, key=lambda item: (item.page_idx, item.reading_order)):
        if prev_block is not None:
            edges.append({
                "id": f"seq-{prev_block.block_id}-{block.block_id}",
                "from": prev_block.block_id,
                "to": block.block_id,
                "kind": "weak",
                "label": "before",
            })
        prev_block = block

    return {
        "nodes": nodes,
        "edges": edges,
        "stats": {
            "nodes_count": len(nodes),
            "edges_count": len(edges),
            "outline_count": len(document.outlines),
            "generated_by": generated_by,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_document_segments(
    document: CanonicalDocument,
    block_line_ranges: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """从 CanonicalDocument 构建 document_segments 列表（popo 格式）。"""
    line_map = {item["block_id"]: item for item in block_line_ranges}
    segments: List[Dict[str, Any]] = []
    for block in document.blocks:
        line_info = line_map.get(block.block_id, {})
        segments.append({
            "id": f"seg-{block.block_id}",
            "item_type": block.block_type,
            "title": block.section_path.split("/")[-1] if block.section_path else block.text[:50],
            "content": block.text,
            "order_index": block.reading_order,
            "meta": {
                "block_uid": block.block_id,
                "page_idx": block.page_idx,
                "block_type": block.block_type,
                "section_path": block.section_path,
                "title_level": block.title_level,
                "raw_popo_id": block.source_ref,
                "markdown_line_start": line_info.get("markdown_line_start"),
                "markdown_line_end": line_info.get("markdown_line_end"),
                "contd_target_id": block.contd_target_id,
                "image_assoc_id": block.image_assoc_id,
                "table_merge_id": block.table_merge_id,
            },
        })
    return segments


def _build_content_json(block: CanonicalBlock) -> Dict[str, Any]:
    """popo 行 content_json：表格 HTML / 公式文本 / raw_type 直接可达。"""
    payload: Dict[str, Any] = {}
    if block.block_type == "table" and block.table_html:
        payload["table_html"] = block.table_html
    if block.block_type == "formula":
        formula_text = ""
        if block.formula_semantics:
            formula_text = str(block.formula_semantics.get("formula_text") or "")
        payload["math_content"] = formula_text or block.text
    if block.raw_type:
        payload["raw_type"] = block.raw_type
    return payload


def build_doc_block_rows(
    document: CanonicalDocument,
    *,
    derive_version: str = "v1",
    parser_version: str = "popo-4b",
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """G4/P11：统一 base_rows + derived_rows；popo 行携带 table_html / math_content。"""
    now = datetime.now().isoformat()
    doc_id = document.doc_id
    ordered = sorted(document.blocks, key=lambda block: (block.page_idx, block.reading_order))
    prev_uid: Dict[str, Optional[str]] = {}
    next_uid: Dict[str, Optional[str]] = {}
    for index, block in enumerate(ordered):
        prev_uid[block.block_id] = ordered[index - 1].block_id if index > 0 else None
        next_uid[block.block_id] = ordered[index + 1].block_id if index + 1 < len(ordered) else None

    base_rows: List[Dict[str, Any]] = []
    derived_rows: List[Dict[str, Any]] = []
    for block in document.blocks:
        bbox = _bbox_array(block) or [0.0, 0.0, 0.0, 0.0]
        base_rows.append({
            "doc_id": doc_id,
            "doc_name": doc_id,
            "page_idx": block.page_idx,
            "page_width": 0.0,
            "page_height": 0.0,
            "block_seq": block.reading_order,
            "block_uid": block.block_id,
            "block_type": block.block_type,
            "content_json": _build_content_json(block),
            "plain_text": block.text,
            "bbox_abs_x1": bbox[0],
            "bbox_abs_y1": bbox[1],
            "bbox_abs_x2": bbox[2],
            "bbox_abs_y2": bbox[3],
            "created_at": now,
            "updated_at": now,
        })
        math_content = block.text if block.block_type == "formula" else None
        derived_rows.append({
            "doc_id": doc_id,
            "block_uid": block.block_id,
            "page_seq": block.page_idx + 1,
            "bbox_norm_x1": bbox[0],
            "bbox_norm_y1": bbox[1],
            "bbox_norm_x2": bbox[2],
            "bbox_norm_y2": bbox[3],
            "bbox_source": "mineru-popo",
            "raw_title_level": block.title_level,
            "derived_title_level": block.title_level,
            "title_path": block.section_path,
            "parent_block_uid": block.parent_block_id,
            "prev_block_uid": prev_uid.get(block.block_id),
            "next_block_uid": next_uid.get(block.block_id),
            "table_html": block.table_html,
            "math_content": math_content,
            "derived_confidence": None,
            "derived_by": "mineru-popo",
            "derive_version": derive_version,
            "parser_version": parser_version,
            "updated_at": now,
        })
    return base_rows, derived_rows


def write_canonical_products(
    library_id: str,
    doc_id: str,
    document: CanonicalDocument,
    *,
    generated_by: str = "mineru-popo",
    strategy: str = "doc_blocks_graph_v1",
    build_id: Optional[str] = None,
    derive_version: str = "v1",
    parser_version: str = "popo-4b",
    content_md_path: Optional[Path] = None,
    graph_jsonl_path: Optional[Path] = None,
    graph_meta_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """从 CanonicalDocument 统一落盘 content.md / graph jsonl+meta / segments / doc_blocks 行。"""
    import docs_core.paths as paths
    from docs_core.write.store.doc_blocks_graph import new_or_reuse_build_id
    from docs_core.write.store.blocks_sql_store import get_index_store

    resolved_build_id = build_id or new_or_reuse_build_id(library_id, doc_id)

    # content.md + 行号映射（同一 build_id，孪生配对）
    md_text, block_line_ranges = render_content_md(document.blocks, resolved_build_id)
    md_path = Path(content_md_path) if content_md_path else (
        paths.get_parsed_markdown_path(library_id, doc_id)
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")

    # doc_blocks_graph.jsonl + meta
    graph_data = build_doc_blocks_graph(document, block_line_ranges, generated_by=generated_by)
    jsonl_path = Path(graph_jsonl_path) if graph_jsonl_path else paths.get_graph_jsonl_path(library_id, doc_id)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in graph_data["nodes"]:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    meta_path = Path(graph_meta_path) if graph_meta_path else paths.get_graph_meta_path(library_id, doc_id)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    meta = {
        "edges": graph_data["edges"],
        "stats": graph_data["stats"],
        "generated_at": graph_data["generated_at"],
        "build_id": resolved_build_id,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    # document_segments
    segments = build_document_segments(document, block_line_ranges)
    index_store = get_index_store()
    index_store.clear_document_segments(doc_id)
    saved_segments = index_store.save_document_segments(doc_id, library_id, strategy, segments)

    # doc_blocks 主索引：base_rows + derived_rows
    base_rows, derived_rows = build_doc_block_rows(
        document,
        derive_version=derive_version,
        parser_version=parser_version,
    )
    index_store.clear_doc_blocks(doc_id)
    inserted = index_store.insert_doc_blocks_base_rows(base_rows) if base_rows else 0
    updated = index_store.update_doc_blocks_derived_rows(derived_rows) if derived_rows else 0

    return {
        "build_id": resolved_build_id,
        "content_md_path": str(md_path),
        "graph_path": str(jsonl_path),
        "segments_count": saved_segments,
        "base_rows_count": inserted,
        "derived_rows_count": updated,
        "block_line_ranges": block_line_ranges,
        "stats": graph_data["stats"],
    }


__all__ = [
    "build_doc_block_rows",
    "build_doc_blocks_graph",
    "build_document_segments",
    "render_content_md",
    "write_canonical_products",
]
