"""???????/??/??/??/??/???? + ????? canonical??????????"""
import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import docs_core.paths as paths
from docs_core.step04_structure.shared.formula_semantics import build_formula_representations
from docs_core.step04_structure.solo_engine import extract_media_bbox_list
from docs_core.step04_structure.shared.jsonl_io import (
    _write_doc_blocks_graph,
    get_doc_blocks_graph,
)

logger = logging.getLogger(__name__)
from docs_core.step05_sqlite_fts.store.blocks_sql_store import get_index_store
import docs_core.docs_file_io as _afs

__all__ = [
    "batch_operate_doc_blocks",
    "undo_last_doc_block_merge",
    "undo_last_doc_block_operation",
    "update_doc_block_content",
]



# 基于最新审核图谱重canonical，确保检索读模型与编辑结果一致（builder 纯构建，落库由本层负责）
def _rebuild_canonical_after_graph_change(
    library_id: str,
    doc_id: str,
    graph_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, int]:
    from docs_core.step05_sqlite_fts.rebuild.canonical_builder import CanonicalSourceInput
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import rebuild_canonical_document
    from docs_core.docs_service import docs_service

    graph_payload = (
        graph_data
        if graph_data is not None
        else (get_doc_blocks_graph(library_id, doc_id) or {})
    )
    source = CanonicalSourceInput(
        graph_data=graph_payload,
        raw_blocks=_afs.file_storage.read_mineru_blocks(library_id, doc_id) or [],
        markdown=_afs.file_storage.read_markdown(library_id, doc_id) or "",
        manifest=_afs.file_storage.get_doc_manifest(library_id, doc_id),
    )
    canonical_document = rebuild_canonical_document(library_id, doc_id, source=source)
    docs_service.save_canonical_document(canonical_document)
    return {
        "canonical_blocks": len(canonical_document.blocks),
        "canonical_chunks": len(canonical_document.chunks),
        "canonical_tables": len(canonical_document.tables),
    }


# 编辑后重渲染 Markdown 投影：以 jsonl 节点为唯一真相，重写 parsed/content.md 与
# edited/current.md（同一 build_id），并回填节点 markdown 行号映射（须在写 jsonl 前调用）
def _rewrite_markdown_after_graph_change(
    library_id: str,
    doc_id: str,
    graph_data: Dict[str, Any],
) -> str:
    from docs_core.step04_structure.shared.jsonl_io import (
        extract_build_id_from_meta,
        new_or_reuse_build_id,
    )

    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    build_id = ""
    if meta_path.exists():
        try:
            build_id = extract_build_id_from_meta(json.loads(meta_path.read_text(encoding="utf-8"))) or ""
        except (OSError, json.JSONDecodeError):
            build_id = ""
    if not build_id:
        build_id = new_or_reuse_build_id(library_id, doc_id)

    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import build_node_text

    active_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    lines: List[str] = [f"<!-- build_id: {build_id} -->"]
    line_ranges: Dict[str, Dict[str, int]] = {}
    for node in active_nodes:
        uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        text = build_node_text(node)
        if not uid or not text:
            continue
        start = len(lines) + 1
        lines.extend(text.splitlines())
        line_ranges[uid] = {"start": start, "end": len(lines)}
    md_text = "\n".join(lines) + ("\n" if lines else "")

    for node in active_nodes:
        uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        span = line_ranges.get(uid)
        node["markdown_line_start"] = span["start"] if span else None
        node["markdown_line_end"] = span["end"] if span else None

    parsed_md = paths.get_parsed_markdown_path(library_id, doc_id)
    parsed_md.parent.mkdir(parents=True, exist_ok=True)
    parsed_md.write_text(md_text, encoding="utf-8")
    edited_md = paths.get_edited_markdown_path(library_id, doc_id)
    edited_md.parent.mkdir(parents=True, exist_ok=True)
    edited_md.write_text(md_text, encoding="utf-8")
    return build_id


# 编辑后同步知识图谱（步骤七）：LLM 提取较慢，失败不阻断编辑，仅记录状态
def _push_graph_after_edit(library_id: str, doc_id: str) -> str:
    try:
        from docs_core.step07_graph.push_to_graph import push_to_graph

        result = push_to_graph(library_id, doc_id)
        if not result.get("pushed"):
            return str(result.get("error") or "图谱未更新")
        return f"{result.get('entities_count', 0)}实体/{result.get('relations_count', 0)}关系"
    except Exception as exc:  # noqa: BLE001
        return f"图谱更新失败: {exc}"


# 判断节点引用是否命中指定 block_uid
def _matches_block_ref(value: Any, block_uid: str) -> bool:
    if isinstance(value, list):
        return any(_matches_block_ref(item, block_uid) for item in value)
    return str(value or "").strip() == block_uid


# 规范block_uid，统一空值处理
def _normalize_block_uid(value: Any) -> str:
    return str(value or "").strip()


# 仅返回图谱中当前仍然生效的节点集合
def _get_active_graph_nodes(graph_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [
        node
        for node in (graph_data.get("nodes") or [])
        if int(node.get("is_active", 1) or 0) != 0
    ]


# 构block_uid 到节点的快速索引
def _build_active_node_map(graph_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    node_map: Dict[str, Dict[str, Any]] = {}
    for node in _get_active_graph_nodes(graph_data):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid:
            node_map[block_uid] = node
    return node_map


# 按页面与块序对节点做稳定排序，便于重建结构投影
def _sort_graph_nodes(nodes: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(
        nodes,
        key=lambda node: (
            int(node.get("page_idx") or 0),
            int(node.get("block_seq") or 0),
            _normalize_block_uid(node.get("block_uid") or node.get("id")),
        ),
    )


# 按稳定顺序回写图谱节点数组，避免前端树视图读取到旧顺序
def _sort_graph_data_nodes(graph_data: Dict[str, Any]) -> None:
    graph_data["nodes"] = _sort_graph_nodes(_get_active_graph_nodes(graph_data))


# 获取指定节点及其规范block_uid
def _get_graph_node_or_raise(graph_data: Dict[str, Any], block_id: str) -> Any:
    target_block_uid = _normalize_block_uid(block_id)
    for node in _get_active_graph_nodes(graph_data):
        candidate_ids = {
            _normalize_block_uid(node.get("id")),
            _normalize_block_uid(node.get("block_uid")),
        }
        if target_block_uid in candidate_ids:
            resolved_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
            return node, resolved_uid
    raise KeyError(f"未找到块节点: {block_id}")


# 判断候选父节点是否会形成祖先环
def _would_create_cycle(node_map: Dict[str, Dict[str, Any]], node_uid: str, candidate_parent_uid: Optional[str]) -> bool:
    cursor = _normalize_block_uid(candidate_parent_uid)
    visited = set()
    while cursor:
        if cursor == node_uid:
            return True
        if cursor in visited:
            return True
        visited.add(cursor)
        parent = node_map.get(cursor)
        if not parent:
            return False
        cursor = _normalize_block_uid(parent.get("parent_uid"))
    return False


# 解析节点到根节点的祖先路径
def _resolve_parent_chain(node_map: Dict[str, Dict[str, Any]], parent_uid: Optional[str]) -> List[str]:
    chain: List[str] = []
    cursor = _normalize_block_uid(parent_uid)
    visited = set()
    while cursor and cursor not in visited:
        visited.add(cursor)
        parent = node_map.get(cursor)
        if not parent:
            break
        chain.append(cursor)
        cursor = _normalize_block_uid(parent.get("parent_uid"))
    chain.reverse()
    return chain


# 根据目标标题层级推断最近的上级结构节点
def _infer_parent_uid_from_level(
    active_nodes: List[Dict[str, Any]],
    target_block_uid: str,
    target_level: Optional[int],
) -> Optional[str]:
    if target_level is None or target_level <= 1:
        return None
    latest_by_level: Dict[int, str] = {}
    for node in _sort_graph_nodes(active_nodes):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if not block_uid:
            continue
        if block_uid == target_block_uid:
            break
        derived_level = node.get("derived_level")
        if derived_level is None or derived_level == "":
            continue
        try:
            normalized_level = int(derived_level)
        except (TypeError, ValueError):
            continue
        if normalized_level < 1:
            continue
        latest_by_level[normalized_level] = block_uid
        for stale_level in [level for level in latest_by_level.keys() if level > normalized_level]:
            latest_by_level.pop(stale_level, None)
    return latest_by_level.get(int(target_level) - 1)


# 把单值或数组中的 block 引用从旧 uid 替换为新 uid
def _replace_block_ref(value: Any, source_uid: str, target_uid: str) -> Any:
    if isinstance(value, list):
        replaced = [_replace_block_ref(item, source_uid, target_uid) for item in value]
        return [item for item in replaced if _normalize_block_uid(item)]
    return target_uid if _matches_block_ref(value, source_uid) else value


# 合并两个文本字段，避免重复内容
def _merge_text_value(primary: Any, secondary: Any) -> str:
    primary_text = str(primary or "").strip()
    secondary_text = str(secondary or "").strip()
    if not primary_text:
        return secondary_text
    if not secondary_text or secondary_text == primary_text:
        return primary_text
    return f"{primary_text}\n{secondary_text}"


# 归一化并去重节点合并产生bbox 列表
def _normalize_graph_bbox_list(values: List[Any]) -> List[List[float]]:
    normalized: List[List[float]] = []
    seen = set()
    for bbox in extract_media_bbox_list(values):
        key = tuple(float(item) for item in bbox[:4])
        if key in seen:
            continue
        seen.add(key)
        normalized.append([float(item) for item in bbox[:4]])
    return normalized


# 提取节点当前应保留的所bbox 范围
def _collect_node_bbox_list(node: Dict[str, Any]) -> List[List[float]]:
    values: List[Any] = []
    merged_bboxes = node.get("merged_bboxes")
    if isinstance(merged_bboxes, list):
        values.extend(merged_bboxes)
    bbox = node.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        values.append(list(bbox[:4]))
    return _normalize_graph_bbox_list(values)


# 归一化块引用字段，统一返回去重后的 block_uid 列表
def _collect_block_ref_uids(value: Any) -> List[str]:
    if isinstance(value, list):
        return list(dict.fromkeys(
            uid
            for uid in (_normalize_block_uid(item) for item in value)
            if uid
        ))
    normalized = _normalize_block_uid(value)
    return [normalized] if normalized else []


# 收集节点关联的所有图片路径，兼容单图与多图合并结果
def _collect_node_image_paths(node: Dict[str, Any]) -> List[str]:
    raw_values: List[Any] = []
    image_paths = node.get("image_paths")
    if isinstance(image_paths, list):
        raw_values.extend(image_paths)
    image_path = node.get("image_path")
    if image_path:
        raw_values.append(image_path)
    return list(dict.fromkeys(
        str(value).strip()
        for value in raw_values
        if str(value or "").strip()
    ))


# 深拷贝任JSON 兼容值，避免共享嵌套引用
def _clone_json_compatible(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


# JSON 值生成稳定签名，用于去重合并
def _build_json_signature(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False)


# 合并 content_json 里的富媒体载荷，尽量保留原始结构与顺序
def _merge_content_json_value(primary: Any, secondary: Any) -> Any:
    if primary in (None, "", [], {}):
        return _clone_json_compatible(secondary)
    if secondary in (None, "", [], {}):
        return _clone_json_compatible(primary)
    if isinstance(primary, dict) and isinstance(secondary, dict):
        merged: Dict[str, Any] = {}
        for key in dict.fromkeys([*primary.keys(), *secondary.keys()]):
            if key in primary and key in secondary:
                merged[key] = _merge_content_json_value(primary[key], secondary[key])
            elif key in primary:
                merged[key] = _clone_json_compatible(primary[key])
            else:
                merged[key] = _clone_json_compatible(secondary[key])
        return merged
    if isinstance(primary, list) and isinstance(secondary, list):
        merged_list: List[Any] = []
        seen = set()
        for item in [*primary, *secondary]:
            signature = _build_json_signature(item)
            if signature in seen:
                continue
            seen.add(signature)
            merged_list.append(_clone_json_compatible(item))
        return merged_list
    return _clone_json_compatible(primary)


# 把多个节点的富媒体字段聚合到目标节点，避免合并后图片与注释信息丢失
def _merge_rich_media_fields_into_target(target_node: Dict[str, Any], merged_nodes: List[Dict[str, Any]]) -> None:
    if not merged_nodes:
        return

    image_paths: List[str] = []
    caption_block_uids: List[str] = []
    footnote_block_uids: List[str] = []
    caption_bboxes: List[List[float]] = []
    footnote_bboxes: List[List[float]] = []
    merged_content_json: Dict[str, Any] = {}
    rich_media_order: List[Dict[str, Any]] = []

    for node in merged_nodes:
        node_content_json = node.get("content_json")
        if isinstance(node_content_json, dict):
            merged_content_json = _merge_content_json_value(merged_content_json, node_content_json)
        
        node_image_paths = _collect_node_image_paths(node)
        image_paths.extend(node_image_paths)
        
        for img_path in node_image_paths:
            rich_media_order.append({"type": "image", "path": img_path})
        
        if node.get("table_html") and str(node.get("table_html") or "").strip():
            rich_media_order.append({"type": "table"})
        
        if node.get("math_content") and str(node.get("math_content") or "").strip():
            rich_media_order.append({"type": "math"})
        
        caption_block_uids.extend(_collect_block_ref_uids(node.get("caption_block_uid")))
        caption_block_uids.extend(_collect_block_ref_uids(node.get("caption_block_uids")))
        footnote_block_uids.extend(_collect_block_ref_uids(node.get("footnote_block_uid")))
        footnote_block_uids.extend(_collect_block_ref_uids(node.get("footnote_block_uids")))
        caption_bboxes.extend(_normalize_graph_bbox_list(node.get("caption_bboxes")) or [])
        footnote_bboxes.extend(_normalize_graph_bbox_list(node.get("footnote_bboxes")) or [])

    target_node["content_json"] = merged_content_json or {}
    normalized_image_paths = list(dict.fromkeys(image_paths))
    target_node["image_path"] = normalized_image_paths[0] if normalized_image_paths else None
    target_node["image_paths"] = normalized_image_paths or None
    target_node["caption_block_uids"] = list(dict.fromkeys(caption_block_uids)) or None
    target_node["caption_block_uid"] = target_node["caption_block_uids"][0] if target_node.get("caption_block_uids") else None
    target_node["footnote_block_uids"] = list(dict.fromkeys(footnote_block_uids)) or None
    target_node["footnote_block_uid"] = target_node["footnote_block_uids"][0] if target_node.get("footnote_block_uids") else None
    target_node["caption_bboxes"] = _normalize_graph_bbox_list(caption_bboxes) or None
    target_node["footnote_bboxes"] = _normalize_graph_bbox_list(footnote_bboxes) or None
    target_node["rich_media_order"] = rich_media_order or None
    _sync_caption_bboxes_to_content_json(target_node, caption_bboxes, footnote_bboxes)


# 把合并后caption/footnote bbox 同步写入 content_json，确保前端联动能正确读取
def _sync_caption_bboxes_to_content_json(
    target_node: Dict[str, Any],
    caption_bboxes: List[List[float]],
    footnote_bboxes: List[List[float]]
) -> None:
    block_type = str(target_node.get("block_type") or "").strip().lower()
    if block_type not in ("image", "table"):
        return
    content_json = target_node.get("content_json")
    if not isinstance(content_json, dict):
        content_json = {}
        target_node["content_json"] = content_json
    normalized_caption_bboxes = _normalize_graph_bbox_list(caption_bboxes)
    normalized_footnote_bboxes = _normalize_graph_bbox_list(footnote_bboxes)
    if block_type == "table":
        if normalized_caption_bboxes:
            content_json["table_caption_bboxes"] = normalized_caption_bboxes
        if normalized_footnote_bboxes:
            content_json["table_footnote_bboxes"] = normalized_footnote_bboxes
    else:
        if normalized_caption_bboxes:
            content_json["image_caption_bboxes"] = normalized_caption_bboxes
        if normalized_footnote_bboxes:
            content_json["image_footnote_bboxes"] = normalized_footnote_bboxes


# 提取节点当前应保留的合并来源 block_uid 列表
def _collect_node_merge_block_uids(node: Dict[str, Any]) -> List[str]:
    ordered_uids: List[str] = []
    for value in node.get("merged_block_uids") or []:
        block_uid = _normalize_block_uid(value)
        if block_uid and block_uid not in ordered_uids:
            ordered_uids.append(block_uid)
    current_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
    if current_uid and current_uid not in ordered_uids:
        ordered_uids.append(current_uid)
    return ordered_uids


# 同步引用当前节点的题注与脚注显示字段
def _sync_related_graph_fields(nodes: List[Dict[str, Any]], target_block_uid: str, target_node: Dict[str, Any]) -> None:
    caption_text = str(
        target_node.get("plain_text_corrected")
        or target_node.get("plain_text")
        or target_node.get("caption_corrected")
        or target_node.get("caption")
        or ""
    ).strip()
    footnote_text = str(
        target_node.get("plain_text_corrected")
        or target_node.get("plain_text")
        or target_node.get("footnote_corrected")
        or target_node.get("footnote")
        or ""
    ).strip()
    for node in nodes:
        if _matches_block_ref(node.get("caption_block_uid"), target_block_uid) or _matches_block_ref(node.get("caption_block_uids"), target_block_uid):
            node["caption"] = caption_text
        if _matches_block_ref(node.get("footnote_block_uid"), target_block_uid) or _matches_block_ref(node.get("footnote_block_uids"), target_block_uid):
            node["footnote"] = footnote_text


# 依据当前节点关系重建图谱边、前后关系与 title_path
def _rebuild_graph_projection(graph_data: Dict[str, Any]) -> None:
    active_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    node_map = _build_active_node_map({"nodes": active_nodes})
    for node in active_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        node["block_uid"] = block_uid
        if not node.get("id"):
            node["id"] = block_uid
        parent_uid = _normalize_block_uid(node.get("parent_uid"))
        if not parent_uid or parent_uid not in node_map or parent_uid == block_uid or _would_create_cycle(node_map, block_uid, parent_uid):
            parent_uid = ""
        node["parent_uid"] = parent_uid or None
        derived_level = node.get("derived_level")
        if derived_level is not None and derived_level != "":
            try:
                node["derived_level"] = int(derived_level)
            except (TypeError, ValueError):
                node["derived_level"] = None
        else:
            node["derived_level"] = None
        parent_chain = _resolve_parent_chain(node_map, node.get("parent_uid"))
        if node.get("derived_level") is not None:
            node["title_path"] = ">".join(parent_chain + [block_uid]) if parent_chain else block_uid
        else:
            node["title_path"] = ">".join(parent_chain) if parent_chain else None

    for index, node in enumerate(active_nodes):
        node["prev_uid"] = _normalize_block_uid(active_nodes[index - 1].get("block_uid")) if index > 0 else None
        node["next_uid"] = _normalize_block_uid(active_nodes[index + 1].get("block_uid")) if index + 1 < len(active_nodes) else None

    edges: List[Dict[str, Any]] = []
    for node in active_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid"))
        parent_uid = _normalize_block_uid(node.get("parent_uid"))
        if parent_uid and parent_uid in node_map:
            edges.append({
                "source": parent_uid,
                "target": block_uid,
                "relation": "contains",
                "strength": "strong",
            })
        prev_uid = _normalize_block_uid(node.get("prev_uid"))
        if prev_uid and prev_uid in node_map:
            edges.append({
                "source": prev_uid,
                "target": block_uid,
                "relation": "next",
                "strength": "weak",
            })
        explain_for_uid = _normalize_block_uid(node.get("explain_for_uid"))
        if explain_for_uid and explain_for_uid in node_map:
            edges.append({
                "source": explain_for_uid,
                "target": block_uid,
                "relation": "explain",
                "strength": "weak",
            })
    graph_data["edges"] = edges

    stats = graph_data.get("stats")
    if not isinstance(stats, dict):
        return
    active_uid_set = {
        _normalize_block_uid(node.get("block_uid"))
        for node in active_nodes
    }
    row_source_map = {uid: node for uid, node in node_map.items() if uid in active_uid_set}
    for row_key in ("base_rows", "derived_rows", "index_rows"):
        rows = stats.get(row_key)
        if not isinstance(rows, list):
            continue
        synced_rows: List[Dict[str, Any]] = []
        for row in rows:
            block_uid = _normalize_block_uid(row.get("block_uid") or row.get("id"))
            node = row_source_map.get(block_uid)
            if not node:
                continue
            row["plain_text"] = node.get("plain_text_corrected") or node.get("plain_text")
            row["table_html"] = node.get("table_html_corrected") or node.get("table_html")
            row["math_content"] = node.get("math_content_corrected") or node.get("math_content")
            row["title_path"] = node.get("title_path")
            row["caption"] = node.get("caption_corrected") or node.get("caption")
            row["footnote"] = node.get("footnote_corrected") or node.get("footnote")
            row["content_json"] = node.get("content_json") if node.get("content_json") is not None else row.get("content_json")
            row["image_path"] = node.get("image_path")
            row["image_paths"] = node.get("image_paths")
            row["caption_block_uid"] = node.get("caption_block_uid")
            row["caption_block_uids"] = node.get("caption_block_uids")
            row["footnote_block_uid"] = node.get("footnote_block_uid")
            row["footnote_block_uids"] = node.get("footnote_block_uids")
            row["caption_bboxes"] = node.get("caption_bboxes")
            row["footnote_bboxes"] = node.get("footnote_bboxes")
            row["merged_bboxes"] = node.get("merged_bboxes")
            row["page_bboxes"] = node.get("page_bboxes")
            row["merged_from"] = node.get("merged_from")
            if row_key != "base_rows":
                row["parent_uid"] = node.get("parent_uid")
                row["parent_block_uid"] = node.get("parent_uid")
                row["derived_level"] = node.get("derived_level")
                row["derived_title_level"] = node.get("derived_level")
            synced_rows.append(row)
        stats[row_key] = synced_rows


# 追加公式摘要和参数投影项，保持图谱编辑后与解析侧展示一致
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


# 从图谱节点重建结构化片段，确保合并和层级调整能实时投影
def _build_structured_segment_items_from_graph(graph_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import build_node_text

    excluded_types = {"page_header", "page_footer", "page_number", "header", "footer"}
    child_nodes_by_parent: Dict[str, List[Dict[str, Any]]] = {}
    active_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    for node in active_nodes:
        parent_uid = _normalize_block_uid(node.get("parent_uid"))
        if not parent_uid:
            continue
        child_nodes_by_parent.setdefault(parent_uid, []).append(node)
    items: List[Dict[str, Any]] = []
    for order_index, node in enumerate(active_nodes):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        block_type = str(node.get("block_type") or "segment").strip() or "segment"
        if block_type in excluded_types:
            continue
        plain_text = build_node_text(node)
        title_path = str(node.get("title_path") or "").strip()
        title = plain_text or title_path or block_uid
        page_idx = int(node.get("page_idx") or 0)
        page_seq = page_idx + 1
        block_seq = int(node.get("block_seq") or 0)
        meta = {
            "block_uid": block_uid,
            "block_type": block_type,
            "page_idx": page_idx,
            "block_seq": block_seq,
            "title_path": node.get("title_path"),
            "caption": node.get("caption"),
            "footnote": node.get("footnote"),
            "table_html": node.get("table_html"),
            "math_content": node.get("math_content"),
            "image_path": node.get("image_path"),
            "image_paths": node.get("image_paths"),
            "caption_bboxes": node.get("caption_bboxes"),
            "footnote_bboxes": node.get("footnote_bboxes"),
            "merged_bboxes": node.get("merged_bboxes"),
            "caption_block_uid": node.get("caption_block_uid"),
            "caption_block_uids": node.get("caption_block_uids"),
            "footnote_block_uid": node.get("footnote_block_uid"),
            "footnote_block_uids": node.get("footnote_block_uids"),
            "parent_uid": node.get("parent_uid"),
            "derived_level": node.get("derived_level"),
            "order_index": order_index,
        }
        if block_type == "equation_interline":
            contract = node.get("formula_semantics")
            if not isinstance(contract, dict) or not contract:
                explanation_lines = [
                    build_node_text(child)
                    for child in child_nodes_by_parent.get(block_uid, [])
                    if str(child.get("block_type") or "").strip() in {"paragraph", "list"}
                    and build_node_text(child)
                ]
                contract = build_formula_representations(
                    formula_text=str(
                        node.get("math_content_corrected")
                        or node.get("math_content")
                        or plain_text
                        or ""
                    ),
                    explanation_lines=explanation_lines,
                    use_llm=False,
                )
            meta.update(
                {
                    "formula_number": contract.get("formula_number"),
                    "formula_param_count": len(contract.get("formula_params") or []),
                    "formula_params": contract.get("formula_params") or None,
                    "formula_summary": contract.get("formula_summary"),
                    "formula_llm_status": contract.get("llm_status"),
                }
            )
        items.append({
            "id": block_uid,
            "item_type": block_type,
            "title": title,
            "content": plain_text or title,
            "meta": {key: value for key, value in meta.items() if value is not None},
            "order_index": len(items),
        })
        if block_type == "equation_interline":
            _append_formula_projection_items(
                items,
                block_uid=block_uid,
                page_idx=page_idx,
                page_seq=page_seq,
                block_seq=block_seq,
                meta=meta,
            )
    return items


# 基于最新图谱节点重写结构化片段的展示字段
def _sync_structured_segments_after_node_update(
    library_id: str,
    doc_id: str,
    graph_data: Dict[str, Any],
) -> int:
    updated_items = _build_structured_segment_items_from_graph(graph_data)
    return get_index_store().save_document_segments(doc_id, library_id, "doc_blocks_graph_v1", updated_items)


# 内容类字段 → corrected 并列字段映射：编辑/修正只写 corrected，原始字段永不修改
_CONTENT_CORRECTED_FIELDS = {
    "plain_text": "plain_text_corrected",
    "math_content": "math_content_corrected",
    "table_html": "table_html_corrected",
    "caption": "caption_corrected",
    "footnote": "footnote_corrected",
}


def _apply_content_corrected_edits(
    node: Dict[str, Any],
    changes: Dict[str, Any],
    *,
    corrected_by: str = "user",
    now: Optional[str] = None,
) -> List[str]:
    """内容类编辑一律写入 <field>_corrected 并列字段，原始字段永不修改。"""
    applied: List[str] = []
    for source_key, corrected_key in _CONTENT_CORRECTED_FIELDS.items():
        if source_key in changes:
            node[corrected_key] = changes.get(source_key)
            applied.append(corrected_key)
    if applied:
        node["corrected_by"] = corrected_by
        node["corrected_at"] = now or datetime.now().isoformat()
    return applied


def _invalidate_edited_formula_semantics(
    graph_data: Dict[str, Any],
    snapshot_before: Dict[str, Any],
) -> List[str]:
    """结构编辑后，对内容或解释上下文发生变化的公式节点清空 formula_semantics。"""
    before_by_uid = {
        _normalize_block_uid(n.get("block_uid") or n.get("id")): n
        for n in (snapshot_before.get("nodes") or [])
    }
    invalidated: List[str] = []
    for node in graph_data.get("nodes") or []:
        uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if str(node.get("block_type") or "").strip() not in ("formula", "equation_interline"):
            continue
        if "formula_semantics" not in node:
            continue
        before = before_by_uid.get(uid)
        before_math = str(
            (before or {}).get("math_content_corrected")
            or (before or {}).get("math_content")
            or ""
        )
        now_math = str(
            node.get("math_content_corrected")
            or node.get("math_content")
            or ""
        )
        before_plain = str(
            (before or {}).get("plain_text_corrected")
            or (before or {}).get("plain_text")
            or ""
        )
        now_plain = str(
            node.get("plain_text_corrected")
            or node.get("plain_text")
            or ""
        )
        before_explain = set(_collect_block_ref_uids((before or {}).get("explanation_uids")))
        now_explain = set(_collect_block_ref_uids(node.get("explanation_uids")))
        if (
            before is None
            or before_math != now_math
            or before_plain != now_plain
            or before_explain != now_explain
        ):
            node.pop("formula_semantics", None)
            invalidated.append(uid)
    return invalidated


# 将源节点内容并入目标节点，并移除源节点
def _merge_graph_nodes(graph_data: Dict[str, Any], source_uid: str, target_uid: str) -> Dict[str, Any]:
    if source_uid == target_uid:
        raise ValueError("不能把 block 合并到自身")
    node_map = _build_active_node_map(graph_data)
    source_node = node_map.get(source_uid)
    target_node = node_map.get(target_uid)
    if not source_node or not target_node:
        raise KeyError("合并目标不存在")
    if _would_create_cycle(node_map, source_uid, target_uid):
        raise ValueError("不能把 block 合并到自己的子节点")

    target_node["plain_text"] = _merge_text_value(target_node.get("plain_text"), source_node.get("plain_text"))
    target_node["caption"] = _merge_text_value(target_node.get("caption"), source_node.get("caption"))
    target_node["footnote"] = _merge_text_value(target_node.get("footnote"), source_node.get("footnote"))
    if not str(target_node.get("math_content") or "").strip():
        target_node["math_content"] = source_node.get("math_content")
    if not str(target_node.get("table_html") or "").strip():
        target_node["table_html"] = source_node.get("table_html")
    _merge_rich_media_fields_into_target(target_node, [target_node, source_node])
    target_node["merged_bboxes"] = _normalize_graph_bbox_list([
        *_collect_node_bbox_list(target_node),
        *_collect_node_bbox_list(source_node),
    ]) or None
    target_node["merged_block_uids"] = list(dict.fromkeys([
        *_collect_node_merge_block_uids(target_node),
        *_collect_node_merge_block_uids(source_node),
    ])) or None

    updated_nodes: List[Dict[str, Any]] = []
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid == source_uid:
            continue
        if _normalize_block_uid(node.get("parent_uid")) == source_uid:
            node["parent_uid"] = target_uid
        node["caption_block_uid"] = _replace_block_ref(node.get("caption_block_uid"), source_uid, target_uid)
        node["caption_block_uids"] = _replace_block_ref(node.get("caption_block_uids"), source_uid, target_uid)
        node["footnote_block_uid"] = _replace_block_ref(node.get("footnote_block_uid"), source_uid, target_uid)
        node["footnote_block_uids"] = _replace_block_ref(node.get("footnote_block_uids"), source_uid, target_uid)
        if _normalize_block_uid(node.get("explain_for_uid")) == source_uid:
            node["explain_for_uid"] = target_uid
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_uid, target_node)
    return target_node


# 深拷贝图谱节点，避免直接复用嵌套引用
def _clone_graph_node(node: Dict[str, Any]) -> Dict[str, Any]:
    return json.loads(json.dumps(node, ensure_ascii=False))


# 规范拆分后新文本节点的类型，避免继续挂着富媒block_type
def _normalize_split_block_type(block_type: Any) -> str:
    normalized = str(block_type or "").strip()
    if normalized in {"title", "heading", "clause", "list", "paragraph"}:
        return normalized
    return "paragraph"


# 为拆分后的新节点生成稳定且唯一block_uid
def _generate_manual_block_uid(doc_id: str) -> str:
    return f"{doc_id}:manual:{uuid.uuid4().hex[:12]}"


# 将当前活动节点按页码拆为可重排的顺序桶
def _build_page_node_buckets(graph_data: Dict[str, Any]) -> Dict[int, List[Dict[str, Any]]]:
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data)):
        page_idx = int(node.get("page_idx") or 0)
        buckets.setdefault(page_idx, []).append(node)
    return buckets


# 根据页面桶重page_idx block_seq，保证跨页重组后的顺序稳定
def _resequence_page_node_buckets(page_buckets: Dict[int, List[Dict[str, Any]]]) -> None:
    for page_idx in sorted(page_buckets.keys()):
        for block_seq, node in enumerate(page_buckets.get(page_idx) or [], start=1):
            node["page_idx"] = int(page_idx)
            node["block_seq"] = int(block_seq)
            node["page_seq"] = int(page_idx) + 1


# 过滤多block 引用，移除已删除节点
def _filter_removed_block_refs(values: Any, removed_uids: Set[str]) -> Optional[List[str]]:
    normalized_values: List[str] = []
    for value in values or []:
        normalized_value = _normalize_block_uid(value)
        if normalized_value and normalized_value not in removed_uids:
            normalized_values.append(normalized_value)
    return normalized_values or None


# 校验并返回批量操作涉及的 block_uid 列表
def _resolve_batch_block_uids(graph_data: Dict[str, Any], block_ids: List[str]) -> List[str]:
    normalized_uids: List[str] = []
    seen = set()
    for raw_block_id in block_ids or []:
        block_uid = _normalize_block_uid(raw_block_id)
        if not block_uid or block_uid in seen:
            continue
        _get_graph_node_or_raise(graph_data, block_uid)
        seen.add(block_uid)
        normalized_uids.append(block_uid)
    if not normalized_uids:
        raise ValueError("至少需要选择一block")
    return normalized_uids


# 把活动图谱节点重建为 doc_blocks 所需的基础行与派生行
def _build_doc_block_projection_rows(doc_id: str, graph_data: Dict[str, Any]) -> Any:
    stats = graph_data.get("stats")
    if not isinstance(stats, dict):
        stats = {}
    base_row_map = {
        _normalize_block_uid(row.get("block_uid")): dict(row)
        for row in (stats.get("base_rows") or [])
        if _normalize_block_uid(row.get("block_uid"))
    }
    derived_row_map = {
        _normalize_block_uid(row.get("block_uid")): dict(row)
        for row in (stats.get("derived_rows") or [])
        if _normalize_block_uid(row.get("block_uid"))
    }
    now = datetime.now().isoformat()
    graph_doc_name = str(graph_data.get("doc_name") or doc_id)
    base_rows: List[Dict[str, Any]] = []
    derived_rows: List[Dict[str, Any]] = []
    for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data)):
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        bbox = node.get("bbox") or [0.0, 0.0, 0.0, 0.0]
        bbox_values = list(bbox)[:4] if isinstance(bbox, list) else [0.0, 0.0, 0.0, 0.0]
        while len(bbox_values) < 4:
            bbox_values.append(0.0)
        base_row = dict(base_row_map.get(block_uid) or {})
        base_row.update({
            "doc_id": doc_id,
            "doc_name": base_row.get("doc_name") or graph_doc_name,
            "page_idx": int(node.get("page_idx") or 0),
            "block_seq": int(node.get("block_seq") or 0),
            "block_uid": block_uid,
            "block_type": node.get("block_type"),
            "content_json": node.get("content_json") if node.get("content_json") is not None else (base_row.get("content_json") or {}),
            "plain_text": node.get("plain_text_corrected") or node.get("plain_text", ""),
            "bbox_abs_x1": bbox_values[0],
            "bbox_abs_y1": bbox_values[1],
            "bbox_abs_x2": bbox_values[2],
            "bbox_abs_y2": bbox_values[3],
            "page_bboxes": node.get("page_bboxes"),
            "merged_from": node.get("merged_from"),
            "created_at": base_row.get("created_at") or now,
            "updated_at": now,
        })
        derived_row = dict(derived_row_map.get(block_uid) or {})
        derived_row.update({
            "doc_id": doc_id,
            "block_uid": block_uid,
            "page_seq": int(node.get("page_idx") or 0) + 1,
            "bbox_source": node.get("bbox_source"),
            "derived_title_level": node.get("derived_level"),
            "title_path": node.get("title_path"),
            "parent_block_uid": node.get("parent_uid"),
            "prev_block_uid": node.get("prev_uid"),
            "next_block_uid": node.get("next_uid"),
            "explain_for_block_uid": node.get("explain_for_uid"),
            "table_html": node.get("table_html_corrected") or node.get("table_html"),
            "math_content": node.get("math_content_corrected") or node.get("math_content"),
            "image_path": node.get("image_path"),
            "derived_confidence": node.get("confidence"),
            "derived_by": node.get("derived_by"),
            "updated_at": now,
        })
        base_rows.append(base_row)
        derived_rows.append(derived_row)
    return base_rows, derived_rows


# 把最新图谱整体同步到 doc_blocks 索引表，覆盖单块与批量结构改动
def _persist_graph_projection_to_index_store(doc_id: str, graph_data: Dict[str, Any]) -> None:
    base_rows, derived_rows = _build_doc_block_projection_rows(doc_id, graph_data)
    get_index_store().clear_doc_blocks(doc_id)
    if base_rows:
        get_index_store().insert_doc_blocks_base_rows(base_rows)
    if derived_rows:
        get_index_store().update_doc_blocks_derived_rows(derived_rows)


# 批量把多个节点内容并入目标节点，并移除其余源节点
def _merge_multiple_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str], target_uid: str) -> Dict[str, Any]:
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    selected_set = set(block_uids)
    if target_uid not in selected_set:
        raise ValueError("目标 block 必须在选中集合中")
    node_map = _build_active_node_map(graph_data)
    target_node = node_map.get(target_uid)
    if not target_node:
        raise KeyError("未找到目block")
    merge_sources = [uid for uid in block_uids if uid != target_uid]
    for source_uid in merge_sources:
        if _would_create_cycle(node_map, source_uid, target_uid):
            raise ValueError("不能把祖先 block 合并到自己的子节点")
    merged_nodes = [
        node for node in ordered_nodes
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in selected_set
    ]
    merged_node_snapshots = [dict(node) for node in merged_nodes]
    target_node["plain_text"] = ""
    target_node["caption"] = ""
    target_node["footnote"] = ""
    target_node["math_content"] = None
    target_node["table_html"] = None
    for node in merged_node_snapshots:
        target_node["plain_text"] = _merge_text_value(target_node.get("plain_text"), node.get("plain_text"))
        target_node["caption"] = _merge_text_value(target_node.get("caption"), node.get("caption"))
        target_node["footnote"] = _merge_text_value(target_node.get("footnote"), node.get("footnote"))
        if not str(target_node.get("math_content") or "").strip() and str(node.get("math_content") or "").strip():
            target_node["math_content"] = node.get("math_content")
        if not str(target_node.get("table_html") or "").strip() and str(node.get("table_html") or "").strip():
            target_node["table_html"] = node.get("table_html")
    _merge_rich_media_fields_into_target(target_node, merged_node_snapshots)
    target_node["merged_bboxes"] = _normalize_graph_bbox_list([
        bbox
        for node in merged_node_snapshots
        for bbox in _collect_node_bbox_list(node)
    ]) or None
    target_node["merged_block_uids"] = list(dict.fromkeys([
        block_uid
        for node in merged_node_snapshots
        for block_uid in _collect_node_merge_block_uids(node)
    ])) or None

    updated_nodes: List[Dict[str, Any]] = []
    merge_source_set = set(merge_sources)
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid in merge_source_set:
            continue
        if _normalize_block_uid(node.get("parent_uid")) in merge_source_set:
            node["parent_uid"] = target_uid
        for source_uid in merge_sources:
            node["caption_block_uid"] = _replace_block_ref(node.get("caption_block_uid"), source_uid, target_uid)
            node["caption_block_uids"] = _replace_block_ref(node.get("caption_block_uids"), source_uid, target_uid)
            node["footnote_block_uid"] = _replace_block_ref(node.get("footnote_block_uid"), source_uid, target_uid)
            node["footnote_block_uids"] = _replace_block_ref(node.get("footnote_block_uids"), source_uid, target_uid)
            if _normalize_block_uid(node.get("explain_for_uid")) == source_uid:
                node["explain_for_uid"] = target_uid
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_uid, target_node)
    return target_node


# 按用户提供的片段把单block 拆成多个连续节点
def _split_graph_node(
    graph_data: Dict[str, Any],
    doc_id: str,
    block_uid: str,
    split_segments: List[Dict[str, Any]],
) -> List[str]:
    normalized_segments = [
        {"plain_text": str((segment or {}).get("plain_text") or "").strip()}
        for segment in (split_segments or [])
    ]
    normalized_segments = [segment for segment in normalized_segments if segment.get("plain_text")]
    if len(normalized_segments) < 2:
        raise ValueError("拆分后至少需要两个非空片段")
    source_node, source_uid = _get_graph_node_or_raise(graph_data, block_uid)
    source_node["plain_text"] = normalized_segments[0]["plain_text"]
    split_block_type = _normalize_split_block_type(source_node.get("block_type"))
    page_buckets = _build_page_node_buckets(graph_data)
    source_page_idx = int(source_node.get("page_idx") or 0)
    page_nodes = page_buckets.get(source_page_idx) or []
    source_index = next(
        (index for index, node in enumerate(page_nodes) if _normalize_block_uid(node.get("block_uid") or node.get("id")) == source_uid),
        -1,
    )
    if source_index < 0:
        raise KeyError(f"未找到块节点: {block_uid}")
    created_nodes: List[Dict[str, Any]] = []
    created_block_ids: List[str] = []
    for segment in normalized_segments[1:]:
        new_node = _clone_graph_node(source_node)
        new_block_uid = _generate_manual_block_uid(doc_id)
        new_node["id"] = new_block_uid
        new_node["block_uid"] = new_block_uid
        new_node["block_type"] = split_block_type
        new_node["plain_text"] = segment["plain_text"]
        new_node["math_content"] = None
        new_node["table_html"] = None
        new_node["caption"] = None
        new_node["footnote"] = None
        new_node["image_path"] = None
        new_node["image_paths"] = None
        new_node["caption_block_uid"] = None
        new_node["caption_block_uids"] = None
        new_node["caption_bboxes"] = None
        new_node["footnote_block_uid"] = None
        new_node["footnote_block_uids"] = None
        new_node["footnote_bboxes"] = None
        new_node["merged_bboxes"] = None
        new_node["merged_block_uids"] = None
        new_node["content_json"] = {}
        new_node["prev_uid"] = None
        new_node["next_uid"] = None
        created_nodes.append(new_node)
        created_block_ids.append(new_block_uid)
    page_nodes[source_index + 1:source_index + 1] = created_nodes
    graph_data["nodes"].extend(created_nodes)
    _resequence_page_node_buckets(page_buckets)
    _sort_graph_data_nodes(graph_data)
    return created_block_ids


# 删除选中block，并把仍保留的子节点提升到最近的存活父级
def _delete_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str]) -> List[str]:
    delete_uid_set = set(block_uids)
    ordered_delete_uids = [
        _normalize_block_uid(node.get("block_uid") or node.get("id"))
        for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data))
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in delete_uid_set
    ]
    delete_uids = set(ordered_delete_uids)
    if not delete_uids:
        raise ValueError("至少需要删除一block")

    node_map = _build_active_node_map(graph_data)
    parent_map = {
        block_uid: _normalize_block_uid(node.get("parent_uid")) or None
        for block_uid, node in node_map.items()
    }

    def resolve_surviving_parent(parent_uid: Any) -> Optional[str]:
        current_uid = _normalize_block_uid(parent_uid) or None
        visited: Set[str] = set()
        while current_uid and current_uid in delete_uids and current_uid not in visited:
            visited.add(current_uid)
            current_uid = parent_map.get(current_uid)
        return current_uid or None

    updated_nodes: List[Dict[str, Any]] = []
    for node in graph_data.get("nodes") or []:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid in delete_uids:
            continue
        node["parent_uid"] = resolve_surviving_parent(node.get("parent_uid"))
        if _normalize_block_uid(node.get("caption_block_uid")) in delete_uids:
            node["caption_block_uid"] = None
        node["caption_block_uids"] = _filter_removed_block_refs(node.get("caption_block_uids"), delete_uids)
        if _normalize_block_uid(node.get("footnote_block_uid")) in delete_uids:
            node["footnote_block_uid"] = None
        node["footnote_block_uids"] = _filter_removed_block_refs(node.get("footnote_block_uids"), delete_uids)
        if _normalize_block_uid(node.get("explain_for_uid")) in delete_uids:
            node["explain_for_uid"] = None
        updated_nodes.append(node)
    graph_data["nodes"] = updated_nodes
    page_buckets = _build_page_node_buckets(graph_data)
    _resequence_page_node_buckets(page_buckets)
    _sort_graph_data_nodes(graph_data)
    return ordered_delete_uids


# 将选中block 跨页移动到目标页，并支持插入到指定锚点之后
def _reorganize_graph_nodes(
    graph_data: Dict[str, Any],
    block_uids: List[str],
    target_page_idx: Optional[int],
    insert_after_block_uid: Optional[str],
    parent_block_uid: Optional[str],
    derived_title_level: Optional[int],
) -> List[str]:
    selected_set = set(block_uids)
    node_map = _build_active_node_map(graph_data)
    if parent_block_uid and parent_block_uid in selected_set:
        raise ValueError("目标父节点不能包含在移动集合中")
    page_buckets = _build_page_node_buckets(graph_data)
    moving_nodes: List[Dict[str, Any]] = []
    for page_idx, nodes in list(page_buckets.items()):
        retained_nodes: List[Dict[str, Any]] = []
        for node in nodes:
            block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
            if block_uid in selected_set:
                moving_nodes.append(node)
            else:
                retained_nodes.append(node)
        page_buckets[page_idx] = retained_nodes
    if not moving_nodes:
        raise ValueError("未找到可移动block")

    target_page_value = int(target_page_idx) if target_page_idx is not None else None
    insertion_index = None
    if insert_after_block_uid:
        insert_after_uid = _normalize_block_uid(insert_after_block_uid)
        if insert_after_uid in selected_set:
            raise ValueError("插入锚点不能位于当前移动集合中")
        anchor_node = node_map.get(insert_after_uid)
        if not anchor_node:
            raise KeyError(f"未找到插入锚 {insert_after_uid}")
        target_page_value = int(anchor_node.get("page_idx") or 0)
        target_nodes = page_buckets.setdefault(target_page_value, [])
        insertion_index = next(
            (index for index, node in enumerate(target_nodes) if _normalize_block_uid(node.get("block_uid") or node.get("id")) == insert_after_uid),
            len(target_nodes) - 1,
        ) + 1
    if target_page_value is None:
        target_page_value = int(moving_nodes[0].get("page_idx") or 0)

    target_nodes = page_buckets.setdefault(target_page_value, [])
    if insertion_index is None:
        insertion_index = len(target_nodes)
    for node in moving_nodes:
        node["page_idx"] = target_page_value
        if parent_block_uid is not None:
            if parent_block_uid and _would_create_cycle(node_map, _normalize_block_uid(node.get("block_uid") or node.get("id")), parent_block_uid):
                raise ValueError("目标父节点不能设置为自身或子节点")
            node["parent_uid"] = _normalize_block_uid(parent_block_uid) or None
        if derived_title_level is not None:
            node["derived_level"] = int(derived_title_level)
    target_nodes[insertion_index:insertion_index] = moving_nodes
    _resequence_page_node_buckets(page_buckets)
    return [_normalize_block_uid(node.get("block_uid") or node.get("id")) for node in moving_nodes]


# 按批次统一应用多个标题节点的目标层级，并重算它们的父子关系
def _apply_graph_node_levels(graph_data: Dict[str, Any], next_levels: Dict[str, int]) -> List[str]:
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    node_map = _build_active_node_map(graph_data)
    selected_set = set(next_levels.keys())
    ordered_selected_uids = [
        _normalize_block_uid(node.get("block_uid") or node.get("id"))
        for node in ordered_nodes
        if _normalize_block_uid(node.get("block_uid") or node.get("id")) in selected_set
    ]
    if not ordered_selected_uids:
        raise ValueError("未找到可调整层级block")

    latest_by_level: Dict[int, str] = {}
    for node in ordered_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if not block_uid:
            continue
        effective_level = next_levels.get(block_uid)
        if effective_level is not None:
            next_parent_uid = latest_by_level.get(effective_level - 1) if effective_level > 1 else None
            node["derived_level"] = effective_level
            node["parent_uid"] = next_parent_uid
            latest_by_level[effective_level] = block_uid
            for stale_level in [level for level in latest_by_level.keys() if level > effective_level]:
                latest_by_level.pop(stale_level, None)
            continue
        derived_level = node.get("derived_level")
        if derived_level is None or derived_level == "":
            continue
        try:
            normalized_level = int(derived_level)
        except (TypeError, ValueError):
            continue
        if normalized_level < 1:
            continue
        latest_by_level[normalized_level] = block_uid
        for stale_level in [level for level in latest_by_level.keys() if level > normalized_level]:
            latest_by_level.pop(stale_level, None)

    return ordered_selected_uids


# 按批次统一升降多个标题节点的层级，并重算它们的父子关系
def _relevel_graph_nodes(graph_data: Dict[str, Any], block_uids: List[str], level_delta: int) -> List[str]:
    if level_delta == 0:
        raise ValueError("层级调整量不能为 0")
    ordered_nodes = _sort_graph_nodes(_get_active_graph_nodes(graph_data))
    selected_set = set(block_uids)
    next_levels: Dict[str, int] = {}
    for node in ordered_nodes:
        block_uid = _normalize_block_uid(node.get("block_uid") or node.get("id"))
        if block_uid not in selected_set:
            continue
        current_level = node.get("derived_level")
        if current_level is None or current_level == "":
            raise ValueError("批量升降级仅支持已识别为标题的节点")
        try:
            normalized_level = int(current_level)
        except (TypeError, ValueError) as exc:
            raise ValueError("批量升降级仅支持已识别为标题的节点") from exc
        target_level = normalized_level + int(level_delta)
        if target_level < 1:
            raise ValueError("L1 节点不能继续上调一级")
        next_levels[block_uid] = target_level
    return _apply_graph_node_levels(graph_data, next_levels)


# 按批次把多个节点直接设置为指定层级，并重算它们的父子关系
def _set_graph_nodes_level(graph_data: Dict[str, Any], block_uids: List[str], target_level: int) -> List[str]:
    normalized_target_level = int(target_level)
    if normalized_target_level < 1:
        raise ValueError("目标层级必须大于等于 L1")
    next_levels = {
        _normalize_block_uid(block_uid): normalized_target_level
        for block_uid in block_uids
        if _normalize_block_uid(block_uid)
    }
    if not next_levels:
        raise ValueError("未找到可调整层级block")
    return _apply_graph_node_levels(graph_data, next_levels)


# 执行批量结构操作，并同步图谱、索引库与结构化片段
def batch_operate_doc_blocks(
    library_id: str,
    doc_id: str,
    operation: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    graph_data = get_doc_blocks_graph(library_id, doc_id)
    if not graph_data:
        raise FileNotFoundError("文档块图谱不存在")

    block_uids = _resolve_batch_block_uids(graph_data, payload.get("blockIds") or [])
    graph_snapshot_before = _clone_json_compatible(graph_data)
    result_payload = {
        "operation": operation,
        "block_ids": block_uids,
        "created_block_ids": [],
        "removed_block_ids": [],
        "target_block_id": None,
        "updated_block_ids": [],
    }
    if operation == "merge":
        if len(block_uids) < 2:
            raise ValueError("批量合并至少需要选择两个 block")
        target_block_uid = _normalize_block_uid(payload.get("targetBlockId"))
        if not target_block_uid:
            raise ValueError("批量合并必须指定目标 block")
        _merge_multiple_graph_nodes(graph_data, block_uids, target_block_uid)
        result_payload["removed_block_ids"] = [uid for uid in block_uids if uid != target_block_uid]
        result_payload["target_block_id"] = target_block_uid
    elif operation == "split":
        if len(block_uids) != 1:
            raise ValueError("拆分 block 只能选择一个源 block")
        result_payload["created_block_ids"] = _split_graph_node(
            graph_data,
            doc_id,
            block_uids[0],
            payload.get("splitSegments") or [],
        )
    elif operation == "delete":
        result_payload["removed_block_ids"] = _delete_graph_nodes(graph_data, block_uids)
    elif operation == "relevel":
        target_level = payload.get("targetLevel")
        if target_level is not None:
            try:
                normalized_target_level = int(target_level)
            except (TypeError, ValueError) as exc:
                raise ValueError("targetLevel 必须是整数") from exc
            result_payload["updated_block_ids"] = _set_graph_nodes_level(graph_data, block_uids, normalized_target_level)
        else:
            level_delta = payload.get("levelDelta")
            if level_delta is None:
                raise ValueError("批量层级调整必须提供 levelDelta targetLevel")
            try:
                normalized_level_delta = int(level_delta)
            except (TypeError, ValueError) as exc:
                raise ValueError("levelDelta 必须是整数") from exc
            result_payload["updated_block_ids"] = _relevel_graph_nodes(graph_data, block_uids, normalized_level_delta)
    else:
        raise ValueError(f"不支持的批量操作: {operation}")

    invalidated_formulas = _invalidate_edited_formula_semantics(graph_data, graph_snapshot_before)
    if invalidated_formulas:
        logger.info("公式语义失效待重建: %s", invalidated_formulas)

    _rebuild_graph_projection(graph_data)
    _rewrite_markdown_after_graph_change(library_id, doc_id, graph_data)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)

    from docs_core.docs_service import docs_service

    _persist_graph_projection_to_index_store(doc_id, graph_data)
    record_block_uid = _normalize_block_uid(payload.get("targetBlockId")) or block_uids[0]
    correction_payload = dict(payload)
    if operation in {"merge", "split", "delete", "relevel"}:
        correction_payload["undo_graph_snapshot"] = graph_snapshot_before
    get_index_store().record_doc_block_correction(doc_id, record_block_uid, operation, correction_payload)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    canonical_stats = _rebuild_canonical_after_graph_change(library_id, doc_id, graph_data)
    graph_status = _push_graph_after_edit(library_id, doc_id)
    docs_service.update_node(doc_id, updated_at=datetime.now())
    result_payload["graph_path"] = graph_path
    result_payload["saved_segments"] = saved_segments
    result_payload["canonical_stats"] = canonical_stats
    result_payload["graph_status"] = graph_status
    return result_payload


# 撤回当前文档最近一次可回滚block 结构操作，并恢复到操作前的图谱状态
def undo_last_doc_block_operation(library_id: str, doc_id: str) -> Dict[str, Any]:
    from docs_core.docs_service import docs_service

    correction_record = get_index_store().get_latest_doc_block_correction(doc_id)
    if not correction_record:
        raise ValueError("当前文档没有可撤回的结构操作")
    operation_type = str(correction_record.get("operation_type") or "").strip() or "unknown"
    payload = correction_record.get("payload") or {}
    snapshot = payload.get("undo_graph_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("nodes"), list):
        raise ValueError(f"最近一次 {operation_type} 操作不支持撤回")

    graph_data = _clone_json_compatible(snapshot)
    _rebuild_graph_projection(graph_data)
    _sort_graph_data_nodes(graph_data)
    _rewrite_markdown_after_graph_change(library_id, doc_id, graph_data)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)
    _persist_graph_projection_to_index_store(doc_id, graph_data)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    canonical_stats = _rebuild_canonical_after_graph_change(library_id, doc_id, graph_data)
    graph_status = _push_graph_after_edit(library_id, doc_id)
    get_index_store().delete_doc_block_correction(str(correction_record.get("id") or ""))
    docs_service.update_node(doc_id, updated_at=datetime.now())
    return {
        "graph_path": graph_path,
        "saved_segments": saved_segments,
        "canonical_stats": canonical_stats,
        "graph_status": graph_status,
        "restored_block_ids": [
            _normalize_block_uid(node.get("block_uid") or node.get("id"))
            for node in _sort_graph_nodes(_get_active_graph_nodes(graph_data))
            if _normalize_block_uid(node.get("block_uid") or node.get("id"))
        ],
    }


# 兼容旧调用名，统一走最近一次结构操作撤回
def undo_last_doc_block_merge(library_id: str, doc_id: str) -> Dict[str, Any]:
    return undo_last_doc_block_operation(library_id, doc_id)


# 更新单个结构节点的纠错内容并同步索引投影
def update_doc_block_content(
    library_id: str,
    doc_id: str,
    block_id: str,
    changes: Dict[str, Any],
) -> Dict[str, Any]:
    graph_data = get_doc_blocks_graph(library_id, doc_id)
    if not graph_data:
        raise FileNotFoundError("文档块图谱不存在")
    graph_snapshot_before = _clone_json_compatible(graph_data)

    editable_keys = {
        "plain_text",
        "math_content",
        "table_html",
        "title",
        "caption",
        "footnote",
        "parent_block_uid",
        "derived_title_level",
        "merge_into_block_uid",
    }
    normalized_changes = {key: value for key, value in changes.items() if key in editable_keys}
    if not normalized_changes:
        raise ValueError("未提供可更新字段")

    target_node, target_block_uid = _get_graph_node_or_raise(graph_data, block_id)
    source_block_uid = target_block_uid
    node_map = _build_active_node_map(graph_data)

    next_parent_uid = None
    if "parent_block_uid" in normalized_changes:
        next_parent_uid = _normalize_block_uid(normalized_changes.get("parent_block_uid")) or None
        if next_parent_uid and next_parent_uid not in node_map:
            raise KeyError(f"未找到父级节 {next_parent_uid}")
        if _would_create_cycle(node_map, target_block_uid, next_parent_uid):
            raise ValueError("父级节点不能设置为自身或子节点")
        target_node["parent_uid"] = next_parent_uid

    if "derived_title_level" in normalized_changes:
        level_value = normalized_changes.get("derived_title_level")
        target_node["derived_level"] = int(level_value) if level_value is not None else None
        if "parent_block_uid" not in normalized_changes:
            next_parent_uid = _infer_parent_uid_from_level(
                _get_active_graph_nodes(graph_data),
                target_block_uid,
                target_node.get("derived_level"),
            )
            if next_parent_uid and _would_create_cycle(node_map, target_block_uid, next_parent_uid):
                raise ValueError("自动推断出的父级节点形成循环，请手动指定父级节点")
            target_node["parent_uid"] = next_parent_uid
    elif next_parent_uid and target_node.get("derived_level") is not None:
        parent_node = node_map.get(next_parent_uid)
        parent_level = parent_node.get("derived_level") if parent_node else None
        target_node["derived_level"] = int(parent_level) + 1 if parent_level is not None else 1

    _apply_content_corrected_edits(target_node, normalized_changes)
    if "title" in normalized_changes:
        target_node["title_path"] = normalized_changes.get("title")
        if not str(target_node.get("plain_text") or "").strip():
            target_node["plain_text_corrected"] = normalized_changes.get("title")

    merge_target_uid = _normalize_block_uid(normalized_changes.get("merge_into_block_uid"))
    if merge_target_uid:
        target_node = _merge_graph_nodes(graph_data, target_block_uid, merge_target_uid)
        target_block_uid = merge_target_uid

    _rebuild_graph_projection(graph_data)
    _sync_related_graph_fields(graph_data.get("nodes") or [], target_block_uid, target_node)
    _rewrite_markdown_after_graph_change(library_id, doc_id, graph_data)
    graph_data["updated_at"] = datetime.now().isoformat()
    graph_path = _write_doc_blocks_graph(library_id, doc_id, graph_data)

    from docs_core.docs_service import docs_service

    _persist_graph_projection_to_index_store(doc_id, graph_data)
    operation_type = "merge" if merge_target_uid else "update"
    correction_payload = dict(normalized_changes)
    if merge_target_uid:
        correction_payload["undo_graph_snapshot"] = graph_snapshot_before
    get_index_store().record_doc_block_correction(doc_id, target_block_uid, operation_type, correction_payload)
    saved_segments = _sync_structured_segments_after_node_update(library_id, doc_id, graph_data)
    canonical_stats = _rebuild_canonical_after_graph_change(library_id, doc_id, graph_data)
    graph_status = _push_graph_after_edit(library_id, doc_id)
    docs_service.update_node(doc_id, updated_at=datetime.now())

    return {
        "graph_path": graph_path,
        "block_id": target_block_uid,
        "updated_fields": list(normalized_changes.keys()),
        "saved_segments": saved_segments,
        "canonical_stats": canonical_stats,
        "graph_status": graph_status,
        "node": target_node,
    }
