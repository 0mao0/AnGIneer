"""PoPo 结果 → 兼容产物投影层。"""
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from docs_core.read.organize.types import CanonicalBlock, CanonicalOutlineNode

logger = logging.getLogger(__name__)


def generate_build_id() -> str:
    """生成孪生产物版本戳（12 位 hex）。"""
    return uuid4().hex[:12]


def regenerate_content_md(
    blocks: List[CanonicalBlock],
    mineru_content_md: str,
    output_path: str,
    build_id: Optional[str] = None,
) -> List[Dict[str, int]]:
    """以 MinerU content.md 文本为基准，按 PoPo 块顺序重建 content.md。

    同时计算每个 block 的 markdown_line_start / markdown_line_end 并返回。
    若指定 build_id，首行写入 `<!-- build_id: xxx -->` 注释（行号偏移已计入）。
    返回: [{"block_id": str, "markdown_line_start": int, "markdown_line_end": int}]
    """
    sorted_blocks = sorted(blocks, key=lambda b: (b.page_idx, b.reading_order))

    header_lines = [f"<!-- build_id: {build_id} -->"] if build_id else []
    lines: List[str] = list(header_lines)
    block_line_ranges: List[Dict[str, Any]] = []

    for block in sorted_blocks:
        text = block.text_clean or block.text
        if not text:
            continue
        block_lines = text.splitlines()
        start_line = len(lines) + 1
        lines.extend(block_lines)
        end_line = len(lines)
        block_line_ranges.append({
            "block_id": block.block_id,
            "markdown_line_start": start_line,
            "markdown_line_end": end_line,
        })

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
        f.write("\n")

    return block_line_ranges


def build_doc_blocks_graph(
    blocks: List[CanonicalBlock],
    outlines: List[CanonicalOutlineNode],
    block_line_ranges: List[Dict[str, int]],
    base_rows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """从 PoPo blocks + outlines 构建兼容 doc_blocks_graph.json 格式。"""
    line_map = {item["block_id"]: item for item in block_line_ranges}

    nodes = []
    for block in blocks:
        bbox_array = (
            [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
            if block.bbox else None
        )
        node = {
            "id": block.block_id,
            "block_uid": block.block_id,
            "block_type": block.block_type,
            "page_idx": block.page_idx,
            "block_seq": block.reading_order,
            "plain_text": block.text,
            "bbox": bbox_array,
            "bbox_norm_x1": block.bbox.x0 if block.bbox else None,
            "bbox_norm_y1": block.bbox.y0 if block.bbox else None,
            "bbox_norm_x2": block.bbox.x1 if block.bbox else None,
            "bbox_norm_y2": block.bbox.y1 if block.bbox else None,
            "derived_level": block.title_level,
            "title_path": block.section_path,
            "parent_uid": block.parent_block_id,
            "markdown_line_start": line_map.get(block.block_id, {}).get("markdown_line_start"),
            "markdown_line_end": line_map.get(block.block_id, {}).get("markdown_line_end"),
            "contd_target_id": block.contd_target_id,
            "image_assoc_id": block.image_assoc_id,
            "table_merge_id": block.table_merge_id,
            "source": "mineru-popo",
        }
        nodes.append(node)

    edges = []
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

    prev_block = None
    for block in sorted(blocks, key=lambda b: (b.page_idx, b.reading_order)):
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
            "generated_by": "mineru-popo",
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def build_document_segments(
    blocks: List[CanonicalBlock],
    block_line_ranges: List[Dict[str, int]],
) -> List[Dict[str, Any]]:
    """从 PoPo blocks 构建 document_segments 列表。"""
    line_map = {item["block_id"]: item for item in block_line_ranges}
    segments = []
    for block in blocks:
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


def build_base_rows(blocks: List[CanonicalBlock]) -> List[Dict[str, Any]]:
    """从 PoPo blocks 构建 base_rows 兼容投影（doc_blocks 表 schema）。"""
    now = datetime.now().isoformat()
    rows = []
    for block in blocks:
        bbox = (
            [block.bbox.x0, block.bbox.y0, block.bbox.x1, block.bbox.y1]
            if block.bbox else [0.0, 0.0, 0.0, 0.0]
        )
        rows.append({
            "doc_id": block.doc_id,
            "doc_name": block.doc_id,
            "page_idx": block.page_idx,
            "page_width": 0.0,
            "page_height": 0.0,
            "block_seq": block.reading_order,
            "block_uid": block.block_id,
            "block_type": block.block_type,
            "content_json": {},
            "plain_text": block.text,
            "bbox_abs_x1": bbox[0],
            "bbox_abs_y1": bbox[1],
            "bbox_abs_x2": bbox[2],
            "bbox_abs_y2": bbox[3],
            "created_at": now,
            "updated_at": now,
        })
    return rows


def run_popo_projection(
    library_id: str,
    doc_id: str,
    blocks: List[CanonicalBlock],
    outlines: List[CanonicalOutlineNode],
    mineru_content_md: str,
    graph_output_path: str,
    content_md_output_path: str,
) -> Dict[str, Any]:
    """一站式兼容投影：生成 content.md / doc_blocks_graph / segments / base_rows。

    孪生产物（content.md + graph jsonl/meta）写入同一 build_id，保证同源一致。
    """
    build_id = generate_build_id()
    block_line_ranges = regenerate_content_md(blocks, mineru_content_md, content_md_output_path, build_id=build_id)
    segments = build_document_segments(blocks, block_line_ranges)
    base_rows = build_base_rows(blocks)

    graph_data = build_doc_blocks_graph(blocks, outlines, block_line_ranges, base_rows)

    jsonl_path = graph_output_path[: -len(".json")] + ".jsonl" if graph_output_path.endswith(".json") else graph_output_path + ".jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in graph_data["nodes"]:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    meta_path = graph_output_path[: -len(".json")] + "_meta.json" if graph_output_path.endswith(".json") else graph_output_path + "_meta.json"
    meta = {
        "edges": graph_data["edges"],
        "stats": graph_data["stats"],
        "generated_at": graph_data["generated_at"],
        "build_id": build_id,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "graph_path": graph_output_path,
        "content_md_path": content_md_output_path,
        "segments": segments,
        "base_rows": base_rows,
        "block_line_ranges": block_line_ranges,
        "build_id": build_id,
    }
