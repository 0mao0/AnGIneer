"""popo 04 统一写入投影：blocks/outlines → content.md + doc_blocks_graph.jsonl + meta。

04 只负责出 jsonl（块 + 层级 + 表格/公式原始材料与语义），canonical 组装归 05。

- ``build_doc_blocks_graph``：blocks + outlines → 节点/边/meta（含 outlines 投影）；
- ``write_graph_products_from_blocks``：落盘 content.md + graph jsonl + meta。
"""
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.models.types import (
    CanonicalBlock,
    CanonicalOutlineNode,
    CanonicalPage,
)


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
    blocks: List[CanonicalBlock],
    outlines: List[CanonicalOutlineNode],
    block_line_ranges: List[Dict[str, Any]],
    *,
    generated_by: str = "mineru-popo",
) -> Dict[str, Any]:
    """从 blocks + outlines 构建 doc_blocks_graph（jsonl 节点 + 四种边 + stats）。"""
    line_map = {item["block_id"]: item for item in block_line_ranges}
    nodes: List[Dict[str, Any]] = []
    for block in blocks:
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
            **_build_content_json(block),
        })

    edges: List[Dict[str, Any]] = []
    for block in blocks:
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
    for block in sorted(blocks, key=lambda item: (item.page_idx, item.reading_order)):
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
            "outline_count": len(outlines),
            "generated_by": generated_by,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


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
        if block.formula_semantics:
            payload["formula_semantics"] = dict(block.formula_semantics)
    if block.raw_type:
        payload["raw_type"] = block.raw_type
    return payload


def write_graph_products_from_blocks(
    library_id: str,
    doc_id: str,
    *,
    blocks: List[CanonicalBlock],
    outlines: List[CanonicalOutlineNode],
    pages: Optional[List[CanonicalPage]] = None,
    generated_by: str = "mineru-popo",
    build_id: Optional[str] = None,
    content_md_path: Optional[Path] = None,
    graph_jsonl_path: Optional[Path] = None,
    graph_meta_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """从 blocks + outlines 只落盘文件产物（content.md + graph jsonl+meta，含 outlines）。

    SQLite 侧（canonical 表 / doc_blocks 行 / segments / FTS）由阶段六从 jsonl 重建。
    """
    import docs_core.paths as paths
    from docs_core.step04_structure.shared.jsonl_store import new_or_reuse_build_id

    resolved_build_id = build_id or new_or_reuse_build_id(library_id, doc_id)

    # content.md + 行号映射（同一 build_id，孪生配对）
    md_text, block_line_ranges = render_content_md(blocks, resolved_build_id)
    md_path = Path(content_md_path) if content_md_path else (
        paths.get_parsed_markdown_path(library_id, doc_id)
    )
    md_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(md_text, encoding="utf-8")

    # doc_blocks_graph.jsonl + meta
    graph_data = build_doc_blocks_graph(blocks, outlines, block_line_ranges, generated_by=generated_by)
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
        "outlines": [outline.model_dump() for outline in outlines],
        "pages": [page.model_dump() for page in pages] if pages else [],
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "build_id": resolved_build_id,
        "content_md_path": str(md_path),
        "graph_path": str(jsonl_path),
        "block_line_ranges": block_line_ranges,
        "stats": graph_data["stats"],
    }


__all__ = [
    "build_doc_blocks_graph",
    "render_content_md",
    "write_graph_products_from_blocks",
]
