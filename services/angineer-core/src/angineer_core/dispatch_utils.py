"""分级路由辅助（P6d 从 dispatcher.py 下沉）。

文档别名归一、尝试链汇总与最终落点回填；供 dispatch 主流程复用。
"""
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from angineer_core.base_contracts import AttemptedPathResult, IntentResult


def normalize_doc_alias(value: Any) -> str:
    """归一化文档别名，兼容标题、文件名与去扩展名的匹配。"""
    normalized = str(value or "").strip().lower()
    if not normalized:
        return ""
    normalized = normalized.replace("\\", "/").split("/")[-1]
    normalized = re.sub(r"\.(pdf|docx?|md|txt)$", "", normalized)
    normalized = re.sub(r"[\s_.\-]+", "", normalized)
    return normalized


def resolve_requested_doc_ids(doc_nodes: List[Any], requested_doc_ids: List[str]) -> set[str]:
    """把逻辑文档别名映射为当前知识库中的真实运行时 doc_id。"""
    requested = {
        str(doc_id or "").strip()
        for doc_id in (requested_doc_ids or [])
        if str(doc_id or "").strip()
    }
    if not requested:
        return set()
    alias_to_doc_id: Dict[str, str] = {}
    for node in doc_nodes:
        node_id = str(getattr(node, "id", "") or "").strip()
        if not node_id:
            continue
        for candidate in (
            node_id,
            getattr(node, "title", ""),
            os.path.basename(str(getattr(node, "file_path", "") or "")),
            os.path.splitext(os.path.basename(str(getattr(node, "file_path", "") or "")))[0],
        ):
            normalized = normalize_doc_alias(candidate)
            if normalized and normalized not in alias_to_doc_id:
                alias_to_doc_id[normalized] = node_id
    resolved = set()
    for doc_id in requested:
        resolved.add(alias_to_doc_id.get(normalize_doc_alias(doc_id), doc_id))
    return resolved


def append_attempted_path(
    attempted_paths: List[Dict[str, Any]],
    path: str,
    status: str,
    reason: str,
    duration: Optional[float] = None,
) -> None:
    """向尝试链追加一条执行记录。"""
    attempted_paths.append({
        "path": path,
        "status": status,
        "reason": reason,
        "duration": duration,
    })


def summarize_sql_attempt(
    *,
    citations: List[Dict[str, Any]],
    retrieved_items: List[Dict[str, Any]],
    sql_payload: Optional[Dict[str, Any]],
    fallback_used: bool,
) -> Tuple[str, str]:
    """根据 SQL 检索结果给出更准确的尝试状态与说明。"""
    row_count = 0
    execution_status = ""
    if isinstance(sql_payload, dict):
        row_count = int(sql_payload.get("row_count") or 0)
        execution_status = str(sql_payload.get("execution_status") or "")
    evidence_count = max(len(citations), len(retrieved_items), row_count)
    if fallback_used:
        return "failed", "SQL/条款定位执行异常，已转入下一级尝试。"
    if execution_status == "bridged" and evidence_count > 0:
        return "insufficient", "L2 已命中可复用的条文/公式证据，但还需要后续计算链继续收敛最终答案。"
    if evidence_count > 0:
        return "insufficient", "SQL/条款定位已命中部分结构化依据，但这些依据还不足以直接完成最终作答。"
    return "no_match", "SQL/条款定位未找到可直接使用的结构化依据，已转入下一级尝试。"


def summarize_sop_attempt(
    *,
    answer: str,
    fallback_used: bool,
    route_debug: Dict[str, Any],
    flow_debug: Dict[str, Any],
) -> Tuple[str, str]:
    """根据 SOP 路由与执行结果归纳当前尝试状态。"""
    if answer and not fallback_used:
        return "success", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行成功。")
    if not route_debug.get("matched_sop_id"):
        return "no_match", str(route_debug.get("reason") or "未命中标准 SOP。")
    if fallback_used:
        return "failed", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行失败。")
    return "insufficient", str(flow_debug.get("summary") or route_debug.get("reason") or "SOP 执行后仍未得到最终答案。")


def finalize_attempts(
    *,
    intent_result: IntentResult,
    attempted_paths: List[Dict[str, Any]],
) -> Tuple[Optional[str], str]:
    """根据尝试链回填最终落点与回退原因。"""
    final_path = None
    fallback_reason = ""
    for item in attempted_paths:
        if item.get("status") == "success":
            final_path = str(item.get("path") or "")
            break
    if not final_path and attempted_paths:
        final_path = str(attempted_paths[-1].get("path") or "")
    if len(attempted_paths) > 1:
        for item in attempted_paths[:-1]:
            if item.get("status") != "success":
                fallback_reason = str(item.get("reason") or "")
                break
    intent_result.attempted_paths = [
        AttemptedPathResult(
            path=str(item.get("path") or ""),
            status=str(item.get("status") or "skipped"),
            reason=str(item.get("reason") or "") or None,
        )
        for item in attempted_paths
    ]
    intent_result.final_path = final_path  # type: ignore[assignment]
    intent_result.fallback_reason = fallback_reason
    return final_path, fallback_reason
