"""PoPo 层级信号（Phase 8）：enriched 与 document_tree 的候选级别映射。

- Solo 规则层级（derived_level + confidence）为基线；
- PoPo 4B 的 ``level`` 与 document_tree 结构级别经对齐器映射到标题块作候选信号；
- 统一仲裁（resolve_title_levels）在上游 solo2json 管线完成。
"""

import re
from typing import Any, Dict, List, Optional


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


__all__ = [
    "build_popo_level_map",
    "build_popo_tree_level_map",
]
