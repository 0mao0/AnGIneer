"""步骤五（rebuild）：从 doc_blocks_graph jsonl 重建 canonical document（graph 适配 + 重建入口）。

与 step04 的分工：step04 只出 jsonl（含 outlines/pages 投影）；本文件把 jsonl
语义图适配回同包 canonical_builder 可消费的 blocks，并暴露两个"重建"入口：
  ``rebuild_canonical_document_from_graph``（sqlite_index / docs_service 用）与
  ``rebuild_canonical_document``（graph_editor 用）。
"""
import re
from typing import Any, Dict, List, Optional

from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
    CanonicalSourceInput,
    build_canonical_blocks_from_source,
    build_canonical_document_from_blocks,
    clean_text,
    normalize_block_type,
)
from docs_core.models.types import (
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
)


def _coerce_bbox(raw_bbox: object) -> object:
    """把语义图中的 bbox 归一化为 canonical BoundingBox 兼容字典。"""
    if isinstance(raw_bbox, dict):
        return raw_bbox
    if isinstance(raw_bbox, (list, tuple)) and len(raw_bbox) >= 4:
        return {
            "x0": float(raw_bbox[0] or 0.0),
            "y0": float(raw_bbox[1] or 0.0),
            "x1": float(raw_bbox[2] or 0.0),
            "y1": float(raw_bbox[3] or 0.0),
        }
    return None


# 归一化语义图中的章节标题，尽量去掉目录页里尾部页码噪声
def normalize_graph_section_title(text: str) -> str:
    normalized = clean_text(text)
    return re.sub(r"\s*\(\d+\)\s*$", "", normalized)


# 基于图谱父子关系推导当前节点的可读 section_path
def resolve_graph_section_path(
    block_uid: str,
    node_map: dict[str, dict[str, Any]],
    cache: dict[str, str],
) -> str:
    if not block_uid:
        return ""
    cached_value = cache.get(block_uid)
    if cached_value is not None:
        return cached_value
    node = node_map.get(block_uid) or {}
    parent_uid = str(node.get("parent_uid") or "").strip()
    parent_path = resolve_graph_section_path(parent_uid, node_map, cache) if parent_uid else ""
    node_text = normalize_graph_section_title(str(node.get("plain_text") or node.get("text") or "").strip())
    node_block_type = normalize_block_type(node.get("block_type"))
    current_title = ""
    # 仅 title 块参与 section_path 拼装：solo 引擎会给所有块写 derived_level（继承层级），
    # 若按 derived_level 判标题会把每块自身文本追加进路径，破坏同级块同节判定
    if node_text and node_block_type == "title":
        current_title = node_text
    if current_title and parent_path:
        cache[block_uid] = f"{parent_path} / {current_title}"
    else:
        cache[block_uid] = current_title or parent_path
    return cache[block_uid]


# 把单个 doc_blocks_graph 节点适配成 canonical builder 可消费的统一块结构
def adapt_graph_node(raw_node: dict[str, Any], index: int, section_path: str) -> dict[str, Any]:
    block_type = normalize_block_type(raw_node.get("block_type"))
    content_json = raw_node.get("content_json") if isinstance(raw_node.get("content_json"), dict) else {}

    return {
        "id": raw_node.get("id") or f"graph-block-{index}",
        "block_uid": raw_node.get("block_uid") or raw_node.get("id") or f"graph-block-{index}",
        "block_type": block_type,
        "page_idx": raw_node.get("page_idx") or 0,
        "block_seq": raw_node.get("block_seq") or index,
        "text": raw_node.get("plain_text") or "",
        "content": raw_node.get("plain_text") or "",
        "derived_title_level": raw_node.get("derived_level"),
        "title_level": raw_node.get("derived_level"),
        "section_path": section_path,
        "parent_block_uid": raw_node.get("parent_uid"),
        "source_ref": raw_node.get("id"),
        "bbox": _coerce_bbox(raw_node.get("bbox")),
        "table_html": raw_node.get("table_html"),
        "raw_type": raw_node.get("raw_type"),
        "formula_semantics": raw_node.get("formula_semantics"),
        "contd_target_id": raw_node.get("contd_target_id"),
        "image_assoc_id": raw_node.get("image_assoc_id"),
        "table_merge_id": raw_node.get("table_merge_id"),
        "content_json": content_json,
        # 表格标题由 _resolve_table_title 从块文本提取 "表 N..." 行；
        # 不用 plain_text 兜底，否则 popo 合并后的整段文本会整体成为标题。
        "caption": raw_node.get("caption") or "",
        "footnote": raw_node.get("footnote") or "",
    }


# 把整份语义图节点转换为 canonical builder 可消费的最终块结构
def adapt_graph_nodes(graph_nodes: List[dict[str, Any]]) -> List[dict[str, Any]]:
    node_map = {
        str(node.get("block_uid") or node.get("id") or "").strip(): node
        for node in graph_nodes
        if isinstance(node, dict) and str(node.get("block_uid") or node.get("id") or "").strip()
    }
    section_path_cache: dict[str, str] = {}
    adapted_nodes: List[dict[str, Any]] = []
    for index, raw_node in enumerate(graph_nodes):
        if not isinstance(raw_node, dict):
            continue
        block_uid = str(raw_node.get("block_uid") or raw_node.get("id") or "").strip()
        section_path = resolve_graph_section_path(block_uid, node_map, section_path_cache)
        adapted_nodes.append(adapt_graph_node(raw_node, index, section_path))
    return adapted_nodes


def _adapt_source(
    source: CanonicalSourceInput,
) -> tuple[List[dict[str, Any]], Optional[dict[str, dict[str, Any]]]]:
    """从 CanonicalSourceInput 取 blocks：graph 节点优先，否则回退 mineru_blocks。"""
    graph_payload = source.graph_data or {}
    graph_nodes = graph_payload.get("nodes", []) if isinstance(graph_payload, dict) else []
    if graph_nodes:
        adapted = adapt_graph_nodes(graph_nodes)
        node_map = {
            str(item.get("block_uid") or item.get("id") or "").strip(): item
            for item in adapted
            if isinstance(item, dict)
        }
        return adapted, node_map
    return list(source.raw_blocks or []), None


# 直接从给定语义图重建 canonical document
def rebuild_canonical_document_from_graph(
    library_id: str,
    doc_id: str,
    graph_data: dict[str, Any],
    title: str = "",
    *,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    raw_blocks = adapt_graph_nodes(graph_data.get("nodes", []))
    raw_node_map = {
        str(item.get("block_uid") or item.get("id") or "").strip(): item
        for item in raw_blocks
        if isinstance(item, dict)
    }
    outlines = None
    raw_outlines = graph_data.get("outlines") if isinstance(graph_data, dict) else None
    if isinstance(raw_outlines, list):
        outlines = [
            CanonicalOutlineNode(**item)
            for item in raw_outlines
            if isinstance(item, dict)
        ]
    pages = None
    raw_pages = graph_data.get("pages") if isinstance(graph_data, dict) else None
    if isinstance(raw_pages, list):
        pages = [
            CanonicalPage(**item)
            for item in raw_pages
            if isinstance(item, dict)
        ]
    return build_canonical_document_from_blocks(
        library_id,
        doc_id,
        title=title,
        blocks=build_canonical_blocks_from_source(doc_id, raw_blocks),
        outlines=outlines or None,
        pages=pages or None,
        raw_blocks=raw_blocks,
        raw_node_map=raw_node_map,
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )


# 基于最终审核结果重建 canonical document（纯构建，落库由调用方负责）
def rebuild_canonical_document(
    library_id: str,
    doc_id: str,
    title: str = "",
    *,
    source: Optional[CanonicalSourceInput] = None,
    use_llm: bool = False,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
) -> CanonicalDocument:
    src = source or CanonicalSourceInput()
    raw_blocks, raw_node_map = _adapt_source(src)
    return build_canonical_document_from_blocks(
        library_id,
        doc_id,
        title=title,
        blocks=build_canonical_blocks_from_source(doc_id, raw_blocks),
        raw_blocks=raw_blocks,
        raw_node_map=raw_node_map,
        markdown=src.markdown or "",
        manifest=src.manifest or {},
        use_llm=use_llm,
        llm_client=llm_client,
        llm_model=llm_model,
    )


__all__ = [
    "adapt_graph_node",
    "adapt_graph_nodes",
    "rebuild_canonical_document",
    "rebuild_canonical_document_from_graph",
]
