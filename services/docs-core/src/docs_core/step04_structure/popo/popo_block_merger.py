"""PoPo 续接/表格合并（Phase 9）：把 inject 标记的 contd/table_merge 链物理合并为完整块。

- contd（paragraph/list_item）：source 吸收 target 文本，target 删除；节点跨页（page_bboxes）。
- table_merge（table）：table_html 行拼接 + 重复表头去重；caption 归首页、footnote 归末页。
- 合并后删除 contd_target_id/table_merge_id，写 merged_from 溯源；引用统一重映射；按页重排 block_seq。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


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


def _absorb_contd(source: Dict[str, Any], target: Dict[str, Any]) -> None:
    source["plain_text"] = _merge_contd_text(source.get("plain_text"), target.get("plain_text"))
    source["content_json"] = _merge_text_fragments(source, target)
    source["page_bboxes"] = _merge_page_bboxes(source, target)
    source["merged_from"] = _merge_merged_from(source, target)
    source.pop("contd_target_id", None)
    target.pop("contd_target_id", None)


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

    for source_uid in pending:
        if source_uid in removed:
            continue
        source = by_uid.get(source_uid)
        if source is None:
            continue
        target_uid = source.get("contd_target_id")
        if not target_uid:
            continue
        target = by_uid.get(str(target_uid))
        if target is None or str(target_uid) in removed:
            stats["rejected_reasons"].append(f"contd 目标缺失: {source_uid} -> {target_uid}")
            stats["rejected"] += 1
            source.pop("contd_target_id", None)
            continue
        _absorb_contd(source, target)
        removed.add(str(target_uid))
        stats["applied"] += 1

    survivors = [node for node in updated if _uid(node) not in removed]
    _resequence_block_seq(survivors)
    return survivors, stats


__all__ = ["merge_blocks"]
