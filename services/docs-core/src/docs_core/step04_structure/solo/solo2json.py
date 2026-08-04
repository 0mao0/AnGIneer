"""solo ??? 5 ????StructuredResult ? doc_blocks_graph.jsonl + meta?"""
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import docs_core.paths as paths
from docs_core.step04_structure.shared.enrich.formula_semantics import build_formula_representations
from docs_core.step04_structure.solo.solo import StructuredResult, build_structured_from_rawfiles
from docs_core.step04_structure.shared.jsonl_store import (
    _stamp_markdown_build_id,
    new_or_reuse_build_id,
)
import docs_core.assets_file_store as _afs


# 延迟获取 AnGIneer LLM 客户端，避免循环导入
def _get_llm_client():
    try:
        from ai_inference.llm_client import llm_client
        return llm_client
    except ImportError:
        return None


__all__ = ["build_structured_index_for_doc"]



# 保存 doc_blocks_graph.jsonl + doc_blocks_graph_meta.json
def _save_doc_blocks_graph(
    library_id: str,
    doc_id: str,
    result: StructuredResult,
) -> str:
    build_id = new_or_reuse_build_id(library_id, doc_id)
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in result.nodes:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")

    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    meta = {
        "edges": result.edges,
        "stats": result.stats,
        "generated_at": datetime.now().isoformat(),
        "build_id": build_id,
    }
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    _stamp_markdown_build_id(paths.get_parsed_markdown_path(library_id, doc_id), build_id)

    return str(meta_path)


# 归一化文本以提升图表相关块匹配稳定性
def _normalize_related_text(text: str) -> str:
    if not text:
        return ""
    compact = re.sub(r"\s+", "", text)
    compact = re.sub(r"[，。；：、“”‘’（)\[\]【>《.;:!?！？·—\-~]", "", compact)
    return compact.strip().lower()


# 递归收集任意结构中的文本片段
def _collect_texts_from_any(payload: Any) -> List[str]:
    fragments: List[str] = []

    def collect(node: Any) -> None:
        if isinstance(node, str):
            text = node.strip()
            if text:
                fragments.append(text)
            return
        if isinstance(node, list):
            for item in node:
                collect(item)
            return
        if isinstance(node, dict):
            for key in ("content", "text", "value"):
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    fragments.append(value.strip())
            for value in node.values():
                if isinstance(value, (list, dict, str)):
                    collect(value)

    collect(payload)
    return list(dict.fromkeys(fragments))


# 把文本片段转换为可用于跨块匹配的归一化候选
def _build_related_text_needles(values: List[str]) -> List[str]:
    needles: List[str] = []
    for value in values:
        normalized = _normalize_related_text(value)
        if normalized:
            needles.append(normalized)
    filtered = [value for value in needles if len(value) >= 2]
    filtered.sort(key=len, reverse=True)
    return list(dict.fromkeys(filtered))


# 判断文本是否看起来像图表题注编号
def _is_caption_like_text(value: str) -> bool:
    return bool(re.match(r"^(图|表|figure|table)\s*[0-9a-z\u4e00-\u9fa5]", value, re.IGNORECASE))


# 判断候选行文本是否命中图表 caption footnote 文本
def _matches_related_text(row_text: str, needles: List[str]) -> bool:
    if not row_text or not needles:
        return False
    return any(
        needle in row_text
        or (len(row_text) >= 10 and row_text in needle)
        or (isinstance(row_text, str) and _is_caption_like_text(row_text) and needle.startswith(row_text[: min(len(row_text), 32)]))
        for needle in needles
    )


# 为图表块收集同页 caption footnote 的关block_uid
def _collect_media_related_block_refs(
    row: Dict[str, Any],
    rows: List[Dict[str, Any]],
) -> Dict[str, List[str]]:
    block_type = str(row.get("block_type") or "").strip().lower()
    if block_type not in {"image", "table"}:
        return {}

    content_json = row.get("content_json") if isinstance(row.get("content_json"), dict) else {}
    caption_key = "table_caption" if block_type == "table" else "image_caption"
    footnote_key = "table_footnote" if block_type == "table" else "image_footnote"
    caption_needles = _build_related_text_needles(_collect_texts_from_any(content_json.get(caption_key)))
    footnote_needles = _build_related_text_needles(_collect_texts_from_any(content_json.get(footnote_key)))
    if not caption_needles and not footnote_needles:
        return {}

    block_uid = str(row.get("block_uid") or "").strip()
    page_idx = int(row.get("page_idx", -1) or -1)
    excluded_types = {"image", "table", "header", "footer", "page_header", "page_number"}
    caption_refs: List[str] = []
    footnote_refs: List[str] = []

    for candidate in rows:
        candidate_uid = str(candidate.get("block_uid") or candidate.get("id") or "").strip()
        if not candidate_uid or candidate_uid == block_uid:
            continue
        candidate_page_idx = int(candidate.get("page_idx", -1) or -1)
        if candidate_page_idx != page_idx:
            continue
        candidate_type = str(candidate.get("block_type") or candidate.get("type") or "").strip().lower()
        if candidate_type in excluded_types:
            continue
        candidate_text = _normalize_related_text(str(candidate.get("plain_text") or candidate.get("text") or "").strip())
        if not candidate_text:
            continue
        if caption_needles and _matches_related_text(candidate_text, caption_needles):
            caption_refs.append(candidate_uid)
        if footnote_needles and _matches_related_text(candidate_text, footnote_needles):
            footnote_refs.append(candidate_uid)

    result: Dict[str, List[str]] = {}
    if caption_refs:
        result["caption_block_uids"] = list(dict.fromkeys(caption_refs))
    if footnote_refs:
        result["footnote_block_uids"] = list(dict.fromkeys(footnote_refs))
    return result


# 追加公式摘要和参数投影项，保持解析后与图谱重建后的展示一致
def _append_formula_projection_items(
    items: List[Dict[str, Any]],
    *,
    block_uid: str,
    page_idx: int,
    page_seq: int,
    block_seq: int,
    meta: Dict[str, Any],
) -> None:
    formula_params = (meta.get("formula_params") or []) if isinstance(meta, dict) else []
    formula_summary = str(meta.get("formula_summary") or "").strip() if isinstance(meta, dict) else ""
    formula_number = str(meta.get("formula_number") or "").strip() if isinstance(meta, dict) else ""

    if formula_summary:
        items.append(
            {
                "id": f"{block_uid}#summary",
                "item_type": "formula_summary",
                "title": f"公式摘要{f' ({formula_number})' if formula_number else ''}",
                "content": formula_summary,
                "meta": {
                    "block_uid": block_uid,
                    "block_id": block_uid,
                    "source_block_id": block_uid,
                    "formula_block_uid": block_uid,
                    "formula_number": formula_number or None,
                    "page_idx": page_idx,
                    "page_seq": page_seq,
                    "page": page_seq,
                    "block_seq": block_seq,
                    "item_type": "formula_summary",
                },
                "order_index": len(items),
            }
        )

    for param_index, param in enumerate(formula_params):
        symbol = str(param.get("symbol") or "").strip()
        description = str(param.get("description") or "").strip()
        if not symbol or not description:
            continue
        content_parts = [f"{symbol}: {description}"]
        unit = str(param.get("unit") or "").strip()
        reference_hint = str(param.get("reference_hint") or "").strip()
        if unit:
            content_parts.append(f"单位 {unit}")
        if reference_hint:
            content_parts.append(f"来源 {reference_hint}")
        items.append(
            {
                "id": f"{block_uid}#param:{param_index + 1}",
                "item_type": "formula_param",
                "title": symbol,
                "content": " | ".join(content_parts),
                "meta": {
                    "block_uid": block_uid,
                    "block_id": block_uid,
                    "source_block_id": block_uid,
                    "formula_block_uid": block_uid,
                    "formula_number": formula_number or None,
                    "page_idx": page_idx,
                    "page_seq": page_seq,
                    "page": page_seq,
                    "block_seq": block_seq,
                    "parameter_index": param_index + 1,
                    "symbol": symbol,
                    "unit": unit or None,
                    "reference_hint": reference_hint or None,
                    "extracted_by": param.get("extracted_by"),
                    "confidence": param.get("confidence"),
                    "item_type": "formula_param",
                },
                "order_index": len(items),
            }
        )


# 从结构化结果构建 doc_blocks_graph_v1 片段投影
def _build_doc_blocks_graph_segment_items(
    result: StructuredResult,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    use_llm: bool = True,
) -> List[Dict[str, Any]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in result.nodes:
        node_id = str(node.get("block_uid") or node.get("id") or "").strip()
        if node_id:
            node_map[node_id] = node

    derived_map: Dict[str, Dict[str, Any]] = {}
    for row in result.stats.get("derived_rows", []) or []:
        block_uid = str(row.get("block_uid") or "").strip()
        if block_uid:
            derived_map[block_uid] = row

    base_row_map: Dict[str, Dict[str, Any]] = {}
    base_rows: List[Dict[str, Any]] = result.stats.get("base_rows", []) or []
    for row in base_rows:
        block_uid = str(row.get("block_uid") or "").strip()
        if block_uid:
            base_row_map[block_uid] = row

    child_nodes_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    for node in result.nodes:
        parent_uid = str(node.get("parent_uid") or "").strip()
        if not parent_uid:
            continue
        child_nodes_by_parent.setdefault(parent_uid, []).append(node)
    for children in child_nodes_by_parent.values():
        children.sort(
            key=lambda item: (
                int(item.get("page_idx") or 0),
                int(item.get("block_seq") or 0),
                str(item.get("block_uid") or item.get("id") or ""),
            )
        )

    items: List[Dict[str, Any]] = []
    for row in result.index_rows:
        block_uid = str(row.get("block_uid") or "").strip()
        if not block_uid:
            continue

        node = node_map.get(block_uid, {})
        derived_row = derived_map.get(block_uid, {})
        base_row = base_row_map.get(block_uid, {})
        block_type = str(row.get("block_type") or node.get("block_type") or "segment").strip() or "segment"
        page_idx = int(row.get("page_idx", node.get("page_idx", 0)) or 0)
        page_seq = int(derived_row.get("page_seq") or (page_idx + 1))
        block_seq = int(row.get("block_seq", node.get("block_seq", 0)) or 0)
        derived_level = row.get("derived_level")
        parent_block_uid = row.get("parent_uid") or derived_row.get("parent_block_uid")
        plain_text = str(row.get("plain_text") or node.get("plain_text") or "").strip()
        title_path = row.get("title_path") or derived_row.get("title_path")
        fallback_title = f"{block_type}@P{page_seq}B{block_seq}" if block_seq > 0 else f"{block_type}@P{page_seq}"
        title = plain_text or str(title_path or "").strip() or fallback_title
        parser_caption_refs = row.get("caption_block_uids") or node.get("caption_block_uids") or derived_row.get("caption_block_uids") or []
        parser_footnote_refs = row.get("footnote_block_uids") or node.get("footnote_block_uids") or derived_row.get("footnote_block_uids") or []
        caption_block_uids = [str(value).strip() for value in parser_caption_refs if str(value).strip()]
        footnote_block_uids = [str(value).strip() for value in parser_footnote_refs if str(value).strip()]
        caption_bboxes = row.get("caption_bboxes") or node.get("caption_bboxes") or derived_row.get("caption_bboxes")
        footnote_bboxes = row.get("footnote_bboxes") or node.get("footnote_bboxes") or derived_row.get("footnote_bboxes")
        if not caption_block_uids and not footnote_block_uids and base_row:
            related_refs = _collect_media_related_block_refs(base_row, base_rows)
            caption_block_uids = related_refs.get("caption_block_uids", [])
            footnote_block_uids = related_refs.get("footnote_block_uids", [])

        meta = {
            "source": "a_structured_index",
            "block_uid": block_uid,
            "node_id": block_uid,
            "block_id": block_uid,
            "source_block_id": block_uid,
            "block_uids": [block_uid],
            "node_ids": [block_uid],
            "item_type": block_type,
            "page_idx": page_idx,
            "page_seq": page_seq,
            "page": page_seq,
            "block_seq": block_seq,
            "derived_level": derived_level,
            "heading_level": derived_level,
            "level": derived_level,
            "title_path": title_path,
            "parent_uid": parent_block_uid,
            "parent_block_uid": parent_block_uid,
            "caption_block_uid": caption_block_uids[0] if len(caption_block_uids) == 1 else None,
            "caption_block_uids": caption_block_uids or None,
            "caption_bboxes": caption_bboxes,
            "footnote_block_uid": footnote_block_uids[0] if len(footnote_block_uids) == 1 else None,
            "footnote_block_uids": footnote_block_uids or None,
            "footnote_bboxes": footnote_bboxes,
            "bbox": node.get("bbox"),
            "bbox_source": node.get("bbox_source"),
            "derived_by": node.get("derived_by"),
            "confidence": node.get("confidence"),
        }
        meta = {key: value for key, value in meta.items() if value is not None}

        if block_type == "equation_interline":
            explanation_lines = [
                str(child.get("plain_text") or "").strip()
                for child in child_nodes_by_parent.get(block_uid, [])
                if str(child.get("block_type") or "").strip() in {"paragraph", "list"}
                and str(child.get("plain_text") or "").strip()
            ]
            formula_semantics = build_formula_representations(
                formula_text=str(node.get("math_content") or plain_text or ""),
                explanation_lines=explanation_lines,
                llm_client=llm_client,
                llm_model=llm_model,
                use_llm=use_llm,
            )
            meta.update(
                {
                    "formula_number": formula_semantics.get("formula_number"),
                    "formula_param_count": len(formula_semantics.get("formula_params") or []),
                    "formula_params": formula_semantics.get("formula_params") or None,
                    "formula_summary": formula_semantics.get("formula_summary"),
                    "formula_llm_status": formula_semantics.get("llm_status"),
                }
            )
            meta = {key: value for key, value in meta.items() if value is not None}

        items.append(
            {
                "id": block_uid,
                "item_type": block_type,
                "title": title,
                "content": plain_text or title,
                "meta": meta,
                "order_index": len(items),
            }
        )

        if block_type != "equation_interline":
            continue
        _append_formula_projection_items(
            items,
            block_uid=block_uid,
            page_idx=page_idx,
            page_seq=page_seq,
            block_seq=block_seq,
            meta=meta,
        )

    return items


# 为文档构建结构化索引（阶段五：只落 jsonl + meta；SQLite 由阶段六从 jsonl 重建）
def build_structured_index_for_doc(
    library_id: str,
    doc_id: str,
    strategy: str = "doc_blocks_graph_v1",
    options: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    opts = options or {}
    use_llm = opts.get("use_llm", True)
    llm_model = str(opts.get("llm_model") or "").strip() or None
    derive_version = opts.get("derive_version", "v1")

    parsed_dir = paths.get_parsed_dir(library_id, doc_id)
    raw_dir = paths.resolve_canonical_raw_dir(library_id, doc_id)
    paths.resolve_structured_input_dir(raw_dir)

    llm_client = None
    if use_llm:
        llm_client = _get_llm_client()

    doc_name = ""
    doc_info = _afs.file_storage.get_doc_manifest(library_id, doc_id)
    if doc_info.get("source_file"):
        doc_name = Path(doc_info["source_file"]).name

    result = build_structured_from_rawfiles(
        parsed_dir=parsed_dir,
        doc_id=doc_id,
        doc_name=doc_name,
        llm_client=llm_client,
        options={
            "use_llm": use_llm,
            "llm_model": llm_model,
            "derive_version": derive_version,
        },
    )

    if result.stats.get("error"):
        raise ValueError(f"构建结构失败: {result.stats.get('error')}")

    graph_path = _save_doc_blocks_graph(library_id, doc_id, result)

    stats = {
        "nodes_count": len(result.nodes),
        "edges_count": len(result.edges),
        "index_rows_count": len(result.index_rows),
        "llm_status": result.stats.get("llm_status", "disabled"),
        "llm_model": llm_model,
        "derive_version": derive_version,
        "graph_path": graph_path,
    }

    return {
        "saved_count": len(result.nodes),
        "stats": stats,
    }
