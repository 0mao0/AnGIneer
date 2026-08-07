"""PoPo 续接/表格合并（Phase 9）：把 inject 标记的 contd/table_merge 链物理合并为完整块。

- contd（paragraph/list_item）：source 吸收 target 文本，target 删除；节点跨页（page_bboxes）。
- table_merge（table）：table_html 行拼接 + 重复表头去重；caption 归首页、footnote 归末页。
- 合并后删除 contd_target_id/table_merge_id，写 merged_from 溯源；引用统一重映射；按页重排 block_seq。
"""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from docs_core.step04_structure.popo.popo_signal_injector import validate_instruction

logger = logging.getLogger(__name__)

MAX_MERGE_CHAIN = 5


_CAPTION_LIKE_RE = re.compile(r"^\s*(?:续?\s*表|表格|Table|Exhibit)", re.IGNORECASE)


def _uid(node: Dict[str, Any]) -> str:
    return str(node.get("block_uid") or node.get("id") or "").strip()


def _sort_key(node: Dict[str, Any]) -> tuple[int, int]:
    return (int(node.get("page_idx") or 0), int(node.get("block_seq") or 0))


def _merge_contd_text(primary: Any, secondary: Any) -> str:
    primary_text = str(primary or "").strip()
    secondary_text = str(secondary or "").strip()
    if not primary_text:
        return secondary_text
    if not secondary_text or secondary_text == primary_text:
        return primary_text
    return primary_text + secondary_text


def _merge_text_fragments(source: Dict[str, Any], target: Dict[str, Any]) -> Dict[str, Any]:
    """段落/list 的 content_json 文本片段拼接，保持与 plain_text 一致。"""
    src = source.get("content_json") if isinstance(source.get("content_json"), dict) else {}
    tgt = target.get("content_json") if isinstance(target.get("content_json"), dict) else {}
    if "paragraph_content" in src or "paragraph_content" in tgt:
        texts: List[str] = []
        for payload in (src, tgt):
            for item in payload.get("paragraph_content") or []:
                texts.append(str(item.get("content") or ""))
        return {"paragraph_content": [{"type": "text", "content": "".join(texts)}]}
    if "list_items" in src or "list_items" in tgt:
        items: List[Dict[str, Any]] = []
        for payload in (src, tgt):
            for item in payload.get("list_items") or []:
                items.append(dict(item))
        return {**src, "list_items": items}
    return {**src}


def _node_page_bboxes(node: Dict[str, Any]) -> List[Dict[str, Any]]:
    existing = node.get("page_bboxes")
    if isinstance(existing, list) and existing:
        return [dict(item) for item in existing]
    bbox = node.get("bbox")
    if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
        return [{
            "page_idx": int(node.get("page_idx") or 0),
            "bbox": [float(v) for v in bbox[:4]],
        }]
    return []


def _merge_page_bboxes(source: Dict[str, Any], target: Dict[str, Any]) -> List[Dict[str, Any]]:
    merged = [*_node_page_bboxes(source), *_node_page_bboxes(target)]
    seen = set()
    result: List[Dict[str, Any]] = []
    for item in merged:
        key = (int(item.get("page_idx") or 0), tuple(float(v) for v in (item.get("bbox") or [])))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _merge_merged_from(source: Dict[str, Any], target: Dict[str, Any]) -> List[str]:
    merged: List[str] = [str(uid) for uid in (source.get("merged_from") or []) if str(uid).strip()]
    target_uid = _uid(target)
    if target_uid and target_uid not in merged:
        merged.append(target_uid)
    return merged


def _collect_image_paths(node: Dict[str, Any]) -> List[str]:
    """收集节点及其 content_json.image_source 中的图片路径。"""
    paths: List[str] = []
    for value in (node.get("image_paths"), node.get("image_path")):
        if isinstance(value, list):
            for item in value:
                text = str(item or "").strip()
                if text and text not in paths:
                    paths.append(text)
        else:
            text = str(value or "").strip()
            if text and text not in paths:
                paths.append(text)
    content_json = node.get("content_json") if isinstance(node.get("content_json"), dict) else {}
    image_source = content_json.get("image_source")
    if isinstance(image_source, dict):
        text = str(image_source.get("path") or "").strip()
        if text and text not in paths:
            paths.append(text)
    return paths


def _merge_image_paths(source: Dict[str, Any], target: Dict[str, Any]) -> List[str]:
    merged: List[str] = []
    for node in (source, target):
        for path in _collect_image_paths(node):
            if path not in merged:
                merged.append(path)
    return merged


def _absorb_contd(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    source["plain_text"] = _merge_contd_text(source.get("plain_text"), target.get("plain_text"))
    source["content_json"] = _merge_text_fragments(source, target)
    source["page_bboxes"] = _merge_page_bboxes(source, target)
    source["merged_from"] = _merge_merged_from(source, target)
    source.pop("contd_target_id", None)
    target.pop("contd_target_id", None)


def _split_table_rows(table_html: str) -> List[str]:
    return re.findall(r"<tr\b.*?</tr>", table_html or "", flags=re.IGNORECASE | re.DOTALL)


def _row_cell_texts(row_html: str) -> List[str]:
    cells = re.findall(r"<t[dh]\b.*?</t[dh]>", row_html or "", flags=re.IGNORECASE | re.DOTALL)
    texts: List[str] = []
    for cell in cells:
        text = re.sub(r"<[^>]+>", "", cell)
        texts.append(re.sub(r"\s+", "", text))
    return texts


def _merge_table_html(source_html: str, target_html: str) -> str:
    src_rows = _split_table_rows(source_html)
    tgt_rows = _split_table_rows(target_html)
    if not src_rows or not tgt_rows:
        return source_html or target_html
    header_texts = [_row_cell_texts(row) for row in src_rows]
    drop = 0
    while drop < len(tgt_rows) and drop < len(header_texts):
        if _row_cell_texts(tgt_rows[drop]) != header_texts[drop]:
            break
        drop += 1
    body = "".join(tgt_rows[drop:])
    close_index = (source_html or "").lower().rfind("</table>")
    if close_index >= 0:
        return source_html[:close_index] + body + source_html[close_index:]
    return source_html + body


def _merge_table_content_json(
    source_cj: Dict[str, Any], target_cj: Dict[str, Any], merged_html: str
) -> Dict[str, Any]:
    merged = dict(source_cj)
    merged["html"] = merged_html
    footnote_items = [
        *(dict(item) for item in source_cj.get("table_footnote") or []),
        *(dict(item) for item in target_cj.get("table_footnote") or []),
    ]
    if footnote_items:
        merged["table_footnote"] = footnote_items
        merged["table_footnote_bboxes"] = [
            *(list(b) for b in source_cj.get("table_footnote_bboxes") or []),
            *(list(b) for b in target_cj.get("table_footnote_bboxes") or []),
        ]
    return merged


def _collect_fragment_texts(payload: Any) -> List[str]:
    """提取 caption/footnote 片段数组中的纯文本。"""
    texts: List[str] = []
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                value = item.get("content")
                if isinstance(value, str) and value.strip():
                    texts.append(value.strip())
            elif isinstance(item, str) and item.strip():
                texts.append(item.strip())
    elif isinstance(payload, str) and payload.strip():
        texts.append(payload.strip())
    return texts


def _table_caption_text(content_json: Dict[str, Any]) -> str:
    return "".join(_collect_fragment_texts(content_json.get("table_caption"))).strip()


def _table_footnote_text(content_json: Dict[str, Any]) -> str:
    return " ".join(_collect_fragment_texts(content_json.get("table_footnote"))).strip()


def _table_plain_text(content_json: Dict[str, Any]) -> str:
    parts = [
        _table_caption_text(content_json),
        _table_footnote_text(content_json),
    ]
    return " ".join(part for part in parts if part).strip()


def _merge_missing_table_caption(
    source_cj: Dict[str, Any], target_cj: Dict[str, Any]
) -> Dict[str, Any]:
    """source 缺 caption 时，仅当 target caption 像正式表题（表/续表/Table）才继承。"""
    if _table_caption_text(source_cj):
        return source_cj
    target_items = [
        dict(item)
        for item in target_cj.get("table_caption") or []
        if isinstance(item, dict)
    ]
    if not target_items:
        return source_cj
    candidate = "".join(str(item.get("content") or "") for item in target_items).strip()
    if not _CAPTION_LIKE_RE.match(candidate):
        return source_cj
    merged = dict(source_cj)
    merged["table_caption"] = target_items
    if target_cj.get("table_caption_bboxes"):
        merged["table_caption_bboxes"] = [
            list(bbox) for bbox in target_cj.get("table_caption_bboxes") or []
        ]
    return merged


def _absorb_table(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    source_html = str(source.get("table_html") or "")
    target_html = str(target.get("table_html") or "")
    merged_html = _merge_table_html(source_html, target_html)
    source["table_html"] = merged_html
    source_cj = source.get("content_json") if isinstance(source.get("content_json"), dict) else {}
    target_cj = target.get("content_json") if isinstance(target.get("content_json"), dict) else {}
    merged_cj = _merge_table_content_json(source_cj, target_cj, merged_html)
    merged_cj = _merge_missing_table_caption(merged_cj, target_cj)
    source["content_json"] = merged_cj
    source["plain_text"] = (
        _table_plain_text(merged_cj) or str(source.get("plain_text") or "").strip()
    )
    caption_text = _table_caption_text(merged_cj)
    footnote_text = _table_footnote_text(merged_cj)
    source["caption"] = caption_text or str(source.get("caption") or "").strip()
    source["footnote"] = (
        footnote_text
        or _merge_contd_text(source.get("footnote"), target.get("footnote"))
    )
    source["page_bboxes"] = _merge_page_bboxes(source, target)
    source["merged_from"] = _merge_merged_from(source, target)
    image_paths = _merge_image_paths(source, target)
    if image_paths:
        source["image_paths"] = image_paths
        if not source.get("image_path"):
            source["image_path"] = image_paths[0]
    source.pop("table_merge_id", None)
    target.pop("table_merge_id", None)


def _resolve_chain(
    by_uid: Dict[str, Dict[str, Any]],
    source_uid: str,
    kind: str,
    stats: Dict[str, Any],
) -> List[str]:
    chain: List[str] = []
    seen: set[str] = set()
    current = source_uid
    while current:
        if current in seen:
            stats["rejected_reasons"].append(f"{kind} 链成环: {current}")
            stats["rejected"] += 1
            return chain[:1]
        seen.add(current)
        chain.append(current)
        if len(chain) > MAX_MERGE_CHAIN:
            stats["rejected_reasons"].append(f"{kind} 链超过上限: {source_uid}")
            stats["rejected"] += 1
            return chain[:MAX_MERGE_CHAIN]
        node = by_uid.get(current)
        if node is None:
            return chain[:1]
        target_field = "contd_target_id" if kind == "contd" else "table_merge_id"
        target_uid = node.get(target_field)
        if not target_uid:
            return chain
        target = by_uid.get(str(target_uid))
        if target is None:
            stats["rejected_reasons"].append(f"{kind} 目标缺失: {current} -> {target_uid}")
            stats["rejected"] += 1
            return chain[:1]
        instruction = {"kind": kind, "source_uid": current, "target_uid": str(target_uid)}
        ok, reason = validate_instruction(by_uid, instruction)
        if not ok:
            stats["rejected_reasons"].append(f"{kind} {current} -> {target_uid}: {reason}")
            stats["rejected"] += 1
            return chain[:1]
        current = str(target_uid)
    return chain


def _remap_edges(edges: List[Dict[str, Any]], old_uid: str, new_uid: str) -> None:
    for edge in edges or []:
        if edge.get("from") == old_uid:
            edge["from"] = new_uid
        if edge.get("to") == old_uid:
            edge["to"] = new_uid


def _remap_node_refs(nodes: List[Dict[str, Any]], absorb_map: Dict[str, str]) -> None:
    for node in nodes:
        for field in ("parent_uid", "parent_block_uid", "caption_block_uid", "footnote_block_uid", "explain_for_uid"):
            value = str(node.get(field) or "").strip()
            if value in absorb_map:
                node[field] = absorb_map[value]
        for field in ("caption_block_uids", "footnote_block_uids"):
            values = node.get(field)
            if isinstance(values, list):
                remapped = [absorb_map.get(str(item), str(item)) for item in values]
                node[field] = [item for item in remapped if item] or None


def _resequence_block_seq(nodes: List[Dict[str, Any]]) -> None:
    buckets: Dict[int, List[Dict[str, Any]]] = {}
    for node in nodes:
        buckets.setdefault(int(node.get("page_idx") or 0), []).append(node)
    for page_nodes in buckets.values():
        page_nodes.sort(key=lambda node: int(node.get("block_seq") or 0))
        for index, node in enumerate(page_nodes, start=1):
            node["block_seq"] = index


def merge_blocks(
    doc_id: str,
    nodes: List[Dict[str, Any]],
    *,
    edges: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """合并 contd/table_merge 链为完整块。返回 (更新后的 nodes, 统计)。"""
    stats: Dict[str, Any] = {"applied": 0, "rejected": 0, "rejected_reasons": []}
    if not nodes:
        return nodes, stats
    updated = [dict(node) for node in nodes]
    by_uid = {_uid(node): node for node in updated}
    pending = [
        _uid(node)
        for node in updated
        if node.get("contd_target_id") or node.get("table_merge_id")
    ]
    pending.sort(key=lambda uid: _sort_key(by_uid[uid]))
    removed: set[str] = set()
    absorb_map: Dict[str, str] = {}

    for source_uid in pending:
        if source_uid in removed:
            continue
        source = by_uid.get(source_uid)
        if source is None:
            continue
        kind = "contd" if source.get("contd_target_id") else "table_merge"
        chain = _resolve_chain(by_uid, source_uid, kind, stats)
        if len(chain) < 2:
            continue
        for target_uid in chain[1:]:
            target = by_uid.get(target_uid)
            if target is None or target_uid in removed:
                stats["rejected_reasons"].append(f"{kind} 目标已被合并: {target_uid}")
                stats["rejected"] += 1
                break
            if kind == "contd":
                _absorb_contd(source, target)
            else:
                _absorb_table(source, target)
            removed.add(target_uid)
            absorb_map[target_uid] = source_uid
            stats["applied"] += 1
            if edges is not None:
                _remap_edges(edges, target_uid, source_uid)

    _remap_node_refs(updated, absorb_map)
    survivors = [node for node in updated if _uid(node) not in removed]
    _resequence_block_seq(survivors)
    return survivors, stats


__all__ = ["merge_blocks"]
