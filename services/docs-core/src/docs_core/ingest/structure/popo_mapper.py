"""PoPo 输出 → CanonicalBlock / CanonicalOutlineNode 映射层。"""
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from docs_core.ingest.canonical.types import (
    BoundingBox,
    CanonicalBlock,
    CanonicalOutlineNode,
    CanonicalPage,
)
from docs_core.ingest.structure.popo_table_extract import (
    extract_table_html,
    textify_table_html,
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

# 噪声处置表（阶段零）：
# - 纯噪声：直接丢弃（页面级元数据另有去向的除外）
# - 并入宿主：caption/footnote 沿 image / table_merge 关联并入宿主块后丢弃
_PURE_NOISE_TYPES = {"page_title", "header", "footer", "page_footnote", "page_number"}
_MERGE_INTO_HOST_TYPES = {"image_caption", "table_caption", "image_footnote", "table_footnote"}


def _map_popo_type(popo_type: str) -> str:
    return _POPO_TYPE_MAP.get(str(popo_type).strip().lower(), "unknown")


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def _make_block_uid(popo_id: int, doc_id: str) -> str:
    return f"{doc_id}:b{popo_id}"


def _merge_texts_into_hosts(blocks: List[CanonicalBlock], merge_texts: Dict[str, List[str]]) -> None:
    """把 caption/footnote 文本并入宿主块文本（块本身已在上游丢弃）。"""
    for block in blocks:
        merged = merge_texts.get(block.block_id)
        if not merged:
            continue
        extra = "\n".join(text for text in merged if text.strip())
        if not extra:
            continue
        block.text = (block.text + "\n" + extra) if block.text else extra
        block.text_clean = clean_text(block.text)


def build_pages_from_popo(
    doc_id: str,
    po_po_blocks: List[Dict[str, Any]],
    printed_page_labels: Dict[int, str],
) -> List[CanonicalPage]:
    """从 popo blocks 的 page 元数据 + 页码块提取的印刷页码构造页面列表。"""
    seen_pages: set[int] = set()
    for pb in po_po_blocks:
        try:
            seen_pages.add(int(pb.get("page", 1)) - 1)
        except (TypeError, ValueError):
            continue
    if not seen_pages:
        return []
    return [
        CanonicalPage(
            doc_id=doc_id,
            page_idx=page_idx,
            printed_page_label=printed_page_labels.get(page_idx),
        )
        for page_idx in sorted(seen_pages)
    ]


def po_po_blocks_to_canonical(
    doc_id: str,
    po_po_blocks: List[Dict[str, Any]],
    document_tree: Dict[str, Any],
) -> Tuple[List[CanonicalBlock], List[CanonicalOutlineNode], Dict[str, str], List[CanonicalPage]]:
    """将 PoPo enriched blocks + 文档树转换为 CanonicalBlock + CanonicalOutlineNode。

    Returns: (blocks, outlines, id_map, pages)
    - id_map 是 {popo_id_str: canonical_block_id}
    - pages 含 page_idx + printed_page_label（来自 page_number 块文本）
    """
    # Step 1: 建立 PoPo ID → canonical block_id 映射
    id_map: Dict[str, str] = {}
    for pb in po_po_blocks:
        popo_id = str(pb["id"])
        id_map[popo_id] = _make_block_uid(pb["id"], doc_id)

    # Step 1b: 收集噪声块信息（页码 → printed_page_label；caption/footnote → 宿主合并文本）
    printed_page_labels: Dict[int, str] = {}
    merge_texts: Dict[str, List[str]] = {}
    for pb in po_po_blocks:
        popo_type = str(pb.get("type", "")).strip().lower()
        if popo_type == "page_number":
            label = clean_text(pb.get("content", ""))
            if label:
                try:
                    page_idx = int(pb.get("page", 1)) - 1
                except (TypeError, ValueError):
                    continue
                printed_page_labels[page_idx] = label
            continue
        if popo_type not in _MERGE_INTO_HOST_TYPES:
            continue
        host_key = pb.get("image", -1)
        if host_key is None or int(host_key) < 0:
            host_key = pb.get("table_merge", -1)
        host_id = id_map.get(str(host_key)) if host_key is not None and int(host_key) >= 0 else None
        if host_id:
            merge_texts.setdefault(host_id, []).append(str(pb.get("content", "") or ""))

    # Step 2: 从树中提取 section_path 映射
    section_map: Dict[str, str] = {}
    _extract_section_paths(document_tree, "", section_map)

    # Step 3: 从树中提取 parent 映射（block_id → parent_block_id）
    parent_map: Dict[str, Optional[str]] = {}
    _extract_parents(document_tree, None, parent_map, id_map)

    # Step 4: 构建 CanonicalBlock 列表（噪声块在此丢弃）
    blocks: List[CanonicalBlock] = []
    for pb in po_po_blocks:
        popo_id = str(pb["id"])
        popo_type = str(pb.get("type", "text")).strip().lower()
        if popo_type in _PURE_NOISE_TYPES:
            logger.debug("PoPo noise block dropped: id=%s type=%s", pb.get("id"), popo_type)
            continue
        if popo_type in _MERGE_INTO_HOST_TYPES:
            host_key = pb.get("image", -1)
            if host_key is None or int(host_key) < 0:
                host_key = pb.get("table_merge", -1)
            if host_key is not None and int(host_key) >= 0 and id_map.get(str(host_key)):
                logger.debug("PoPo caption/footnote merged into host: id=%s type=%s", pb.get("id"), popo_type)
                continue
            logger.warning("PoPo caption/footnote without host, kept as paragraph: id=%s type=%s", pb.get("id"), popo_type)

        canonical_id = id_map[popo_id]
        block_type = _map_popo_type(popo_type)
        if popo_type in _MERGE_INTO_HOST_TYPES:
            # 无宿主可并入时降级保留为段落，raw_type 仍记原始标签
            block_type = "paragraph"

        # 阶段一（G1）：表格原始 HTML 只进 table_html，text 保留 textified 内容避免污染 FTS
        table_html: Optional[str] = None
        if popo_type == "table":
            table_html = extract_table_html(pb)
        text = textify_table_html(table_html) if table_html else str(pb.get("content", "") or "")

        blocks.append(CanonicalBlock(
            block_id=canonical_id,
            doc_id=doc_id,
            page_idx=int(pb.get("page", 1)) - 1,
            block_type=block_type,
            text=text,
            text_clean=clean_text(text),
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
            raw_type=popo_type,
            table_html=table_html,
        ))

    # Step 4b: caption/footnote 文本并入宿主
    _merge_texts_into_hosts(blocks, merge_texts)

    # Step 5: 构建 CanonicalOutlineNode 列表
    outlines = po_po_tree_to_outlines(doc_id, document_tree, id_map)

    # Step 6: 构建 pages
    pages = build_pages_from_popo(doc_id, po_po_blocks, printed_page_labels)

    return blocks, outlines, id_map, pages


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
            for child in node.get("children", []):
                traverse(child, parent_outline_id, path_parts)
            return
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

    traverse(tree)
    return outlines
