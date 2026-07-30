"""PoPo 输出 → CanonicalBlock / CanonicalOutlineNode 映射层。"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from docs_core.write.ingest.organize.types import (
    BoundingBox,
    CanonicalBlock,
    CanonicalOutlineNode,
)

logger = logging.getLogger(__name__)

_POPO_TYPE_MAP = {
    "title": "title",
    "text": "paragraph",
    "list_item": "list_item",
    "image": "figure",
    "table": "table",
    "image_caption": "figure_caption",
    "table_caption": "table_caption",
    "image_footnote": "footnote",
    "table_footnote": "footnote",
    "page_title": "header_footer",
    "page_number": "header_footer",
    "page_footnote": "header_footer",
    "header": "header_footer",
    "aside_text": "paragraph",
    "footer": "header_footer",
    "equation": "formula",
}


def _map_popo_type(popo_type: str) -> str:
    return _POPO_TYPE_MAP.get(str(popo_type).strip().lower(), "unknown")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _make_block_uid(popo_id: int) -> str:
    return f"b{popo_id}"


def po_po_blocks_to_canonical(
    doc_id: str,
    po_po_blocks: List[Dict[str, Any]],
    document_tree: Dict[str, Any],
) -> Tuple[List[CanonicalBlock], List[CanonicalOutlineNode], Dict[str, str]]:
    """将 PoPo enriched blocks + 文档树转换为 CanonicalBlock + CanonicalOutlineNode。

    Returns: (blocks, outlines, id_map) 其中 id_map 是 {popo_id_str: canonical_block_id}
    """
    # Step 1: 建立 PoPo ID → canonical block_id 映射
    id_map: Dict[str, str] = {}
    for pb in po_po_blocks:
        popo_id = str(pb["id"])
        id_map[popo_id] = _make_block_uid(pb["id"])

    # Step 2: 从树中提取 section_path 映射
    section_map: Dict[str, str] = {}
    _extract_section_paths(document_tree, "", section_map)

    # Step 3: 从树中提取 parent 映射（block_id → parent_block_id）
    parent_map: Dict[str, Optional[str]] = {}
    _extract_parents(document_tree, None, parent_map, id_map)

    # Step 4: 构建 CanonicalBlock 列表
    blocks: List[CanonicalBlock] = []
    for pb in po_po_blocks:
        popo_id = str(pb["id"])
        canonical_id = id_map[popo_id]
        block_type = _map_popo_type(pb.get("type", "text"))

        blocks.append(CanonicalBlock(
            block_id=canonical_id,
            doc_id=doc_id,
            page_idx=int(pb.get("page", 1)) - 1,
            block_type=block_type,
            text=pb.get("content", ""),
            text_clean=clean_text(pb.get("content", "")),
            bbox=BoundingBox(**{
                "x0": float(pb["bbox"][0]), "y0": float(pb["bbox"][1]),
                "x1": float(pb["bbox"][2]), "y1": float(pb["bbox"][3])
            }) if pb.get("bbox") and len(pb["bbox"]) == 4 else None,
            reading_order=int(pb.get("id", 0)),
            title_level=int(pb.get("level")) if pb.get("level") and int(pb.get("level", -1)) > 0 else None,
            section_path=section_map.get(popo_id, ""),
            source="mineru-popo",
            source_ref=popo_id,
            parent_block_id=parent_map.get(popo_id),
            contd_target_id=id_map.get(str(pb.get("contd"))) if pb.get("contd", -1) >= 0 else None,
            image_assoc_id=id_map.get(str(pb.get("image"))) if pb.get("image", -1) >= 0 else None,
            table_merge_id=id_map.get(str(pb.get("table_merge"))) if pb.get("table_merge", -1) >= 0 else None,
        ))

    # Step 5: 构建 CanonicalOutlineNode 列表
    outlines = po_po_tree_to_outlines(doc_id, document_tree, id_map)

    return blocks, outlines, id_map


def _extract_section_paths(tree: dict, prefix: str, result: Dict[str, str]) -> None:
    for child in tree.get("children", []):
        title = child.get("title", "")
        current_path = f"{prefix}/{title}" if prefix and title else (prefix or title)
        for bid in child.get("block_ids", []):
            result[str(bid)] = current_path
        _extract_section_paths(child, current_path, result)


def _extract_parents(
    tree: dict, parent_canonical_id: Optional[str],
    result: Dict[str, Optional[str]], id_map: Dict[str, str],
) -> None:
    for child in tree.get("children", []):
        anchor_bids = child.get("block_ids", [])
        if anchor_bids:
            anchor_id = id_map.get(str(anchor_bids[0]))
        else:
            anchor_id = None
        for bid in child.get("block_ids", []):
            result[str(bid)] = parent_canonical_id
        _extract_parents(child, anchor_id, result, id_map)


def po_po_tree_to_outlines(
    doc_id: str, tree: dict, id_map: Dict[str, str]
) -> List[CanonicalOutlineNode]:
    outlines: List[CanonicalOutlineNode] = []

    def traverse(node: dict, parent_outline_id: Optional[str] = None, path_parts: Optional[List[str]] = None):
        path_parts = path_parts or []
        if node.get("type") == "root":
            pass
        else:
            bid_list = node.get("block_ids", [])
            anchor_id = id_map.get(str(bid_list[0])) if bid_list else str(uuid4())
            title = node.get("title", "")
            current_path = "/".join(path_parts + [title]) if title else "/".join(path_parts)
            outline_id = f"outline-{anchor_id}"
            outlines.append(CanonicalOutlineNode(
                outline_id=outline_id,
                doc_id=doc_id,
                level=node.get("level", 1),
                title=title,
                section_path=current_path,
                page_idx=node.get("location", [{}])[0].get("page", 1) - 1 if node.get("location") else 0,
                anchor_block_id=anchor_id,
                parent_outline_id=parent_outline_id,
            ))
            for child in node.get("children", []):
                traverse(child, outline_id, path_parts + ([title] if title else []))
        for child in node.get("children", []):
            traverse(child, parent_outline_id, path_parts)

    traverse(tree)
    return outlines
