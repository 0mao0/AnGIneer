"""步骤六（SQLite 侧）：CanonicalDocument → doc_blocks 行 / document_segments。"""

from typing import Any, Dict, List, Optional

from docs_core.step04_structure.popo.popo2json import _bbox_array, _build_content_json
from docs_core.models.types import CanonicalBlock, CanonicalDocument


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


def build_doc_block_rows(
    document: CanonicalDocument,
    *,
    derive_version: str = "v1",
    parser_version: str = "popo-4b",
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """G4/P11：统一 base_rows + derived_rows；popo 行携带 table_html / math_content。"""
    from datetime import datetime

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


__all__ = ["build_doc_block_rows", "build_document_segments"]
