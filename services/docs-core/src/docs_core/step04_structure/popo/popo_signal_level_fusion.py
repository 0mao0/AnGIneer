"""PoPo 层级信号融合（Phase 8）：规则基线 + 信号融合 + LLM 仲裁。

- Solo 规则层级（derived_level + confidence）为基线；
- PoPo 4B 的 ``level`` 经对齐器映射到对应标题块作第二信号（不当基线，只作候选）；
- 一致 → 直接采用基线；分歧或低置信 → LLM 仲裁（把 PoPo 层级作为候选写入 prompt）；
- 一致率仅作评估埋点（日志/统计），不参与产出。
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.85


def build_popo_level_map(
    enriched_blocks: List[Dict[str, Any]],
    alignment,
) -> Dict[str, Optional[int]]:
    """source_id → PoPo level（仅 title 类块，level > 0）。"""
    level_map: Dict[str, Optional[int]] = {}
    for block in enriched_blocks:
        level = block.get("level")
        if level is None or int(level) <= 0:
            continue
        source_id = str(block.get("source_id") or "")
        if source_id and source_id in alignment.solo_block_uid_map:
            level_map[source_id] = int(level)
    return level_map


def _normalize_tree_title(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def build_popo_tree_level_map(
    tree: Dict[str, Any],
    enriched_blocks: List[Dict[str, Any]],
    alignment,
) -> Dict[str, int]:
    """document_tree -> {solo_block_uid: level}。

    只取 type=='text' 且 level 在 1..9 的节点；用标题文本匹配 enriched 中的
    title 块（content 归一化相等），经 alignment 映射到 solo uid。
    """
    level_map: Dict[str, int] = {}
    title_by_norm: Dict[str, str] = {}
    for block in enriched_blocks:
        if str(block.get("type") or "") != "title":
            continue
        norm = _normalize_tree_title(block.get("content"))
        if norm:
            title_by_norm.setdefault(norm, str(block.get("source_id") or ""))

    def walk(node: Dict[str, Any]) -> None:
        level = node.get("level")
        title = str(node.get("title") or "")
        if node.get("type") == "text" and title and isinstance(level, int) and 1 <= level <= 9:
            norm = _normalize_tree_title(title)
            source_id = title_by_norm.get(norm)
            uid = alignment.solo_block_uid_map.get(source_id or "")
            if uid:
                level_map[uid] = level
        for child in node.get("children") or []:
            walk(child)

    walk(tree)
    return level_map


def _llm_arbitrate_title_levels(
    disputed: List[Dict[str, Any]],
    popo_level_by_uid: Dict[str, Optional[int]],
    llm_client: Any,
    llm_model: Optional[str],
) -> Tuple[Dict[str, int], str]:
    """LLM 仲裁：rule_level / popo_level 双候选写入 prompt，返回 {block_uid: level}。"""
    mini_items = [
        {
            "block_id": node.get("block_uid") or node.get("id"),
            "text": str(node.get("plain_text") or node.get("text") or "")[:160],
            "rule_level": node.get("derived_level") or node.get("title_level"),
            "popo_level": popo_level_by_uid.get(node.get("block_uid") or node.get("id")),
        }
        for node in disputed
    ]
    system_prompt = (
        "你是文档结构分析器。根据标题文本判断标题级别(>=1，不限制上限)。"
        "rule_level 与 popo_level 仅作候选参考，最终以文本编号为准。"
        '仅返回JSON对象：{"items":[{"block_id":"...","level":1,"confidence":0.95}]}'
    )
    user_prompt = json.dumps({"items": mini_items}, ensure_ascii=False)
    try:
        result_text = llm_client.chat(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            model=llm_model,
        )
        payload = json.loads(str(result_text))
        arr = payload.get("items") if isinstance(payload, dict) else payload
        refined: Dict[str, int] = {}
        if isinstance(arr, list):
            for item in arr:
                if not isinstance(item, dict):
                    continue
                uid = item.get("block_id") or item.get("block_uid")
                level = item.get("level")
                if isinstance(uid, str) and isinstance(level, int) and level >= 1:
                    refined[uid] = level
        return refined, "ok" if refined else "empty_result"
    except Exception as error:
        return {}, f"error:{str(error)[:60]}"


def fuse_level_signals(
    nodes: List[Dict[str, Any]],
    popo_level_by_uid: Dict[str, Optional[int]],
    *,
    llm_client: Any = None,
    llm_model: Optional[str] = None,
    use_llm: bool = False,
    confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """融合 Solo 规则层级与 PoPo 信号，返回 (更新 nodes, 统计埋点)。"""
    title_nodes = [
        node for node in nodes
        if str(node.get("block_type") or "").strip() == "title"
        and str(node.get("plain_text") or node.get("text") or "").strip()
    ]
    stats: Dict[str, Any] = {
        "total_titles": len(title_nodes),
        "popo_signals": 0,
        "consistent": 0,
        "disputed": 0,
        "llm_adopted": 0,
        "consistent_rate": None,
        "llm_status": "disabled",
    }
    if not title_nodes:
        return nodes, stats

    disputed: List[Dict[str, Any]] = []
    for node in title_nodes:
        uid = node.get("block_uid") or node.get("id")
        solo_level = node.get("derived_level") or node.get("title_level")
        popo_level = popo_level_by_uid.get(uid)
        confidence = float(node.get("confidence") or 0.0)
        if popo_level is not None:
            stats["popo_signals"] += 1
            if popo_level == solo_level:
                stats["consistent"] += 1
        if solo_level is None:
            continue
        if confidence >= confidence_threshold:
            continue
        if popo_level is not None and popo_level == solo_level:
            continue
        disputed.append(node)
        stats["disputed"] += 1

    if popo_level_by_uid:
        stats["consistent_rate"] = round(
            stats["consistent"] / stats["popo_signals"], 4
        ) if stats["popo_signals"] else None

    llm_levels: Dict[str, int] = {}
    if disputed and use_llm and llm_client:
        llm_levels, stats["llm_status"] = _llm_arbitrate_title_levels(
            disputed, popo_level_by_uid, llm_client, llm_model
        )
    elif disputed:
        stats["llm_status"] = "disabled"

    if not llm_levels:
        return nodes, stats

    updated = []
    for node in nodes:
        uid = node.get("block_uid") or node.get("id")
        level = llm_levels.get(uid)
        if level is not None and uid in {d.get("block_uid") for d in disputed}:
            node = dict(node)
            node["derived_level"] = level
            node["title_level"] = level
            node["derived_by"] = f"{node.get('derived_by') or 'rule'}+llm"
            node["confidence"] = 0.95
            stats["llm_adopted"] += 1
        updated.append(node)
    return updated, stats


__all__ = [
    "build_popo_level_map",
    "build_popo_tree_level_map",
    "fuse_level_signals",
]
