"""PoPo 续接/表格合并信号注入（Phase 7）。

Solo 是唯一构建者：建块后把对齐后的 PoPo 指令落地为 jsonl 的
``contd_target_id`` / ``table_merge_id`` 标记（块数不变、文本不物理拼接，与
popo 后端 jsonl 输出一致）。每条指令先经规则校验，校验不过拒绝该条合并并记日志；
信号缺失/降级时整体跳过（Solo 永远可独立跑通）。

校验规则：
- 文本续接（contd）：两端均为段落类块、均非标题、按阅读序中间无标题（不跨标题合并）；
- 跨页表格（table_merge）：两端均为表格且列数一致（跨页表格列数一致性）。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from docs_core.step04_structure.popo.popo_signal_aligner import (
    AlignmentResult,
    align_popo_blocks,
)
from docs_core.step04_structure.shared.utils.table_html_utils import parse_table_html

logger = logging.getLogger(__name__)

_CONTINUABLE_TYPES = {"paragraph", "list_item"}


def build_contd_instructions(
    doc_id: str,
    enriched_blocks: List[Dict[str, Any]],
    alignment: AlignmentResult,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """把 enriched 的 contd/table_merge 指令翻译为 solo uid 对。"""
    instructions: List[Dict[str, Any]] = []
    reasons: List[str] = []
    by_id = {
        int(block.get("id", -1)): block
        for block in enriched_blocks
        if block.get("id") is not None
    }
    for block in enriched_blocks:
        contd = block.get("contd")
        table_merge = block.get("table_merge")
        target_id: Optional[int] = None
        kind: Optional[str] = None
        if contd is not None and int(contd) >= 0:
            target_id, kind = int(contd), "contd"
        elif table_merge is not None and int(table_merge) >= 0:
            target_id, kind = int(table_merge), "table_merge"
        if target_id is None or kind is None:
            continue
        target_block = by_id.get(target_id)
        source_uid = alignment.solo_block_uid_map.get(str(block.get("source_id") or ""))
        target_uid = (
            alignment.solo_block_uid_map.get(str(target_block.get("source_id") or ""))
            if target_block is not None
            else None
        )
        if not source_uid or not target_uid:
            reasons.append(
                f"{kind} 指令缺少对齐映射: {block.get('source_id')} -> {target_id}"
            )
            continue
        instructions.append({
            "kind": kind,
            "source_uid": source_uid,
            "target_uid": target_uid,
            "source_source_id": str(block.get("source_id") or ""),
            "target_source_id": str(target_block.get("source_id") or "") if target_block else "",
        })
    return instructions, reasons


def validate_instruction(
    nodes_by_uid: Dict[str, Dict[str, Any]],
    instruction: Dict[str, Any],
) -> Tuple[bool, str]:
    """规则校验单条注入指令（不跨标题 / 类型兼容 / 表格列数一致）。"""
    kind = instruction["kind"]
    source_node = nodes_by_uid.get(instruction["source_uid"])
    target_node = nodes_by_uid.get(instruction["target_uid"])
    if source_node is None or target_node is None:
        return False, "目标块不存在"

    source_type = str(source_node.get("block_type") or "").strip()
    target_type = str(target_node.get("block_type") or "").strip()

    if kind == "contd":
        if source_type not in _CONTINUABLE_TYPES or target_type not in _CONTINUABLE_TYPES:
            return False, f"类型不兼容: {source_type} -> {target_type}"
        if target_type == "title":
            return False, "续接目标为标题（不跨标题合并）"
        # 按 (page_idx, block_seq) 阅读序，两端之间不得有标题
        ordered = sorted(
            nodes_by_uid.values(),
            key=lambda node: (int(node.get("page_idx") or 0), int(node.get("block_seq") or 0)),
        )
        source_seq = (
            int(source_node.get("page_idx") or 0),
            int(source_node.get("block_seq") or 0),
        )
        target_seq = (
            int(target_node.get("page_idx") or 0),
            int(target_node.get("block_seq") or 0),
        )
        if target_seq <= source_seq:
            return False, "续接目标不在源块之后"
        between = [
            node for node in ordered
            if (int(node.get("page_idx") or 0), int(node.get("block_seq") or 0)) > source_seq
            and (int(node.get("page_idx") or 0), int(node.get("block_seq") or 0)) < target_seq
        ]
        if any(str(node.get("block_type") or "").strip() == "title" for node in between):
            return False, "续接跨越标题（不跨标题合并）"
        return True, ""

    if kind == "table_merge":
        if source_type != "table" or target_type != "table":
            return False, f"表格合并类型不兼容: {source_type} -> {target_type}"
        source_cols = _table_column_count(source_node)
        target_cols = _table_column_count(target_node)
        if source_cols != target_cols:
            return False, f"跨页表格列数不一致: {source_cols} != {target_cols}"
        return True, ""

    return False, f"未知指令类型: {kind}"


def _table_column_count(node: Dict[str, Any]) -> int:
    table_html = str(node.get("table_html") or "")
    if not table_html:
        return 0
    rows = parse_table_html(table_html)
    return max((len(row) for row in rows), default=0) if rows else 0


def inject_popo_signals(
    doc_id: str,
    nodes: List[Dict[str, Any]],
    enriched_blocks: List[Dict[str, Any]],
    alignment: AlignmentResult,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """对 solo nodes 应用校验通过的 PoPo 信号，返回 (新 nodes, 统计)。"""
    if alignment.degraded:
        return nodes, {"applied": 0, "rejected": 0, "skipped_reason": "alignment_degraded"}

    instructions, missing_reasons = build_contd_instructions(doc_id, enriched_blocks, alignment)
    nodes_by_uid = {str(node.get("block_uid") or ""): node for node in nodes}
    updated = [dict(node) for node in nodes]
    updated_by_uid = {str(node.get("block_uid") or ""): node for node in updated}

    stats: Dict[str, Any] = {"applied": 0, "rejected": 0, "rejected_reasons": []}
    for reason in missing_reasons:
        stats["rejected_reasons"].append(reason)
        stats["rejected"] += 1

    for instruction in instructions:
        ok, reason = validate_instruction(updated_by_uid, instruction)
        if not ok:
            stats["rejected_reasons"].append(
                f"{instruction['kind']} {instruction['source_uid']} -> "
                f"{instruction['target_uid']}: {reason}"
            )
            stats["rejected"] += 1
            logger.warning(
                "PoPo 信号注入被拒绝: doc=%s %s %s -> %s (%s)",
                doc_id,
                instruction["kind"],
                instruction["source_uid"],
                instruction["target_uid"],
                reason,
            )
            continue
        field = "contd_target_id" if instruction["kind"] == "contd" else "table_merge_id"
        updated_by_uid[instruction["source_uid"]][field] = instruction["target_uid"]
        stats["applied"] += 1

    return updated, stats


__all__ = [
    "build_contd_instructions",
    "inject_popo_signals",
    "validate_instruction",
]
