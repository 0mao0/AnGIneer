"""评测 prediction trace 归一化工具。"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple


def _trace_mode_for_level(intent_level: str) -> str:
    """根据意图层级映射前端展示模式。"""
    if intent_level == "L0":
        return "casual"
    if intent_level in {"L3", "L4"}:
        return "flow"
    return "knowledge"


def _title_for_level(intent_level: str, service_mode: str) -> str:
    """根据意图层级和服务模式返回链路标题。"""
    if intent_level == "L0":
        return "闲聊直答"
    if intent_level == "L2" or service_mode == "sql_first":
        return "SQL/条款定位"
    if intent_level == "L3":
        return "标准 SOP 执行"
    if intent_level == "L4" or service_mode == "dynamic_orchestration":
        return "语义兜底"
    return "知识问答"


def _route_kind_from_service_mode(service_mode: str) -> str:
    """根据 dispatcher 的 service_mode 归一化 route_kind。"""
    mapping = {
        "casual_chat": "none",
        "semantic_retrieval": "retrieval",
        "sql_first": "sql",
        "standard_sop": "standard_sop",
        "dynamic_orchestration": "semantic_fallback",
    }
    return mapping.get(service_mode, "")


def _parse_sop_strategy(strategy: str) -> Tuple[str, float | None]:
    """从旧版策略描述中提取 SOP ID 与 confidence。"""
    match = re.search(
        r"SOP 执行 \((?P<sop_id>[^,]+),\s*confidence=(?P<confidence>\d+(?:\.\d+)?)\)",
        strategy or "",
    )
    if not match:
        return "", None
    sop_id = match.group("sop_id").strip()
    try:
        confidence = float(match.group("confidence"))
    except (TypeError, ValueError):
        confidence = None
    return sop_id, confidence


def _normalize_route_debug(
    raw_data: Dict[str, Any],
    intent: Dict[str, Any],
) -> Dict[str, Any]:
    """把 dispatcher 的路由结果整理为前端稳定结构。"""
    route_debug = dict(raw_data.get("route_debug") or {})
    strategy = str(raw_data.get("strategy") or "")
    service_mode = str(intent.get("service_mode") or "")
    execution_plan = list(route_debug.get("execution_plan") or intent.get("execution_plan") or [])
    attempted_paths = list(route_debug.get("attempted_paths") or intent.get("attempted_paths") or [])
    parsed_sop_id, parsed_confidence = _parse_sop_strategy(strategy)
    route_kind = str(route_debug.get("route_kind") or _route_kind_from_service_mode(service_mode) or "")

    normalized = {
        "route_kind": route_kind,
        "matched_sop_id": str(route_debug.get("matched_sop_id") or parsed_sop_id or ""),
        "matched_sop_name": str(
            route_debug.get("matched_sop_name")
            or route_debug.get("matched_sop_id")
            or parsed_sop_id
            or ""
        ),
        "confidence": route_debug.get("confidence", parsed_confidence),
        "candidates": list(route_debug.get("candidates") or []),
        "args": dict(route_debug.get("args") or {}),
        "missing_args": list(route_debug.get("missing_args") or []),
        "reason": str(route_debug.get("reason") or intent.get("reason") or strategy or ""),
        "primary_level": str(route_debug.get("primary_level") or intent.get("primary_level") or intent.get("intent_level") or ""),
        "execution_plan": execution_plan,
        "attempted_paths": attempted_paths,
        "final_path": str(route_debug.get("final_path") or intent.get("final_path") or ""),
        "fallback_reason": str(route_debug.get("fallback_reason") or intent.get("fallback_reason") or ""),
    }
    return normalized


def _normalize_flow_debug(
    raw_data: Dict[str, Any],
    intent_level: str,
    route_debug: Dict[str, Any],
) -> Dict[str, Any]:
    """把流程执行信息归一化为 L3/L4 可消费的结构。"""
    flow_debug = dict(raw_data.get("flow_debug") or {})
    sop_trace = list(raw_data.get("sop_trace") or [])
    flow_type = str(flow_debug.get("flow_type") or "")
    if not flow_type and intent_level == "L3":
        flow_type = "standard_sop"
    if not flow_type and intent_level == "L4":
        flow_type = "dynamic_sop"

    normalized = {
        "flow_type": flow_type,
        "sop_id": str(flow_debug.get("sop_id") or route_debug.get("matched_sop_id") or ""),
        "sop_name": str(flow_debug.get("sop_name") or route_debug.get("matched_sop_name") or ""),
        "generated_sop": flow_debug.get("generated_sop"),
        "final_context": dict(flow_debug.get("final_context") or {}),
        "summary": str(
            flow_debug.get("summary")
            or (f"共执行 {len(sop_trace)} 个步骤。" if sop_trace else "")
        ),
    }
    return normalized


def _build_trace_issues(
    intent_level: str,
    route_debug: Dict[str, Any],
    flow_debug: Dict[str, Any],
    raw_data: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """根据 prediction 原始字段生成适合前端展示的问题列表。"""
    issues: List[Dict[str, Any]] = []
    sop_trace = list(raw_data.get("sop_trace") or [])
    fallback_used = bool(raw_data.get("fallback_used"))
    sql_payload = raw_data.get("sql") or {}
    execution_plan = list(route_debug.get("execution_plan") or [])

    if fallback_used and len(execution_plan) <= 1:
        issues.append({
            "code": "dispatch_fallback_used",
            "message": "当前题目执行中发生回退，未稳定停留在预期主链。",
        })

    if intent_level in {"L3", "L4"} and not sop_trace:
        issues.append({
            "code": "flow_trace_missing",
            "message": "当前题目标记为流程执行链路，但没有返回步骤追踪。",
        })

    if intent_level == "L3" and not route_debug.get("matched_sop_id"):
        issues.append({
            "code": "route_no_match",
            "message": "当前题目未命中标准 SOP。",
        })

    if route_debug.get("missing_args"):
        issues.append({
            "code": "route_missing_args",
            "message": "SOP 路由存在缺失参数，后续执行可能依赖 LLM 补全。",
            "fields": list(route_debug.get("missing_args") or []),
        })

    step_errors: List[Dict[str, Any]] = []
    hidden_error_steps: List[str] = []
    for step in sop_trace:
        outputs = step.get("outputs") or {}
        output_error = ""
        if isinstance(outputs, dict):
            output_error = str(outputs.get("error") or "")
        step_error = str(step.get("error") or output_error)
        if step_error:
            step_errors.append({
                "step_id": step.get("step_id"),
                "tool": step.get("tool"),
                "message": step_error,
            })
        if step_error and str(step.get("status") or "") == "success":
            hidden_error_steps.append(str(step.get("step_id") or ""))

    if step_errors:
        issues.append({
            "code": "sop_step_error",
            "message": "SOP 步骤中存在显式错误输出。",
            "steps": step_errors,
        })

    if hidden_error_steps:
        issues.append({
            "code": "step_error_hidden_by_success_status",
            "message": "部分步骤输出已包含 error，但状态仍显示为 success。",
            "steps": hidden_error_steps,
        })

    if intent_level == "L2":
        execution_status = str(sql_payload.get("execution_status") or raw_data.get("execution_status") or "")
        if execution_status and execution_status not in {"success", "empty", "unsupported"}:
            issues.append({
                "code": "sql_execution_failed",
                "message": f"SQL 执行状态为 {execution_status}。",
            })

    if intent_level in {"L3", "L4"} and flow_debug.get("summary") == "":
        issues.append({
            "code": "flow_summary_missing",
            "message": "流程执行摘要为空，建议补齐 flow_debug.summary。",
        })

    return issues


def _build_trace_summary(
    trace_meta: Dict[str, Any],
    route_debug: Dict[str, Any],
    issues: List[Dict[str, Any]],
) -> str:
    """根据级别、路由和问题列表生成简短诊断摘要。"""
    issue_codes = {issue.get("code") for issue in issues}
    level = str(trace_meta.get("level") or "")

    if "dispatch_fallback_used" in issue_codes:
        return "当前题目执行过程中发生回退，建议优先检查路由判定与下游能力是否稳定。"
    if "route_no_match" in issue_codes:
        return "当前题目没有命中标准 SOP，建议先检查 SOP 候选召回与参数抽取。"
    if "sop_step_error" in issue_codes:
        return "当前题目已进入流程执行链路，但步骤执行中仍存在显式错误。"
    if level == "L0":
        return "当前题目走闲聊直答链路。"
    if level == "L2":
        final_path = str(route_debug.get("final_path") or "")
        if final_path and final_path != "sql_first":
            final_path_label = {
                "semantic_retrieval": "L1 语义检索",
                "standard_sop": "L3 标准 SOP",
                "dynamic_orchestration": "L4 语义兜底",
            }.get(final_path, final_path)
            return f"当前题目从 L2 起步，最终由 `{final_path_label}` 完成收敛。"
        return "当前题目走 SQL/条款定位链路。"
    matched_sop_id = str(route_debug.get("matched_sop_id") or "")
    if matched_sop_id:
        return f"当前题目已命中 `{matched_sop_id}`，链路结构完整。"
    return "当前题目 trace 结构已生成，可继续结合详情查看具体阶段。"


def enrich_prediction_trace(
    question: Dict[str, Any],
    raw_data: Dict[str, Any],
    prediction: Dict[str, Any],
) -> Dict[str, Any]:
    """把 dispatcher 原始返回补齐为前端稳定消费的 trace 结构。"""
    intent = dict(raw_data.get("intent") or prediction.get("intent") or {})
    intent_level = str(intent.get("intent_level") or question.get("intent_level") or "L1")
    service_mode = str(intent.get("service_mode") or "")
    route_debug = _normalize_route_debug(raw_data, intent)
    flow_debug = _normalize_flow_debug(raw_data, intent_level, route_debug)

    trace_meta = {
        "level": intent_level,
        "primary_level": str(intent.get("primary_level") or intent_level),
        "trace_mode": _trace_mode_for_level(intent_level),
        "service_mode": service_mode,
        "title": _title_for_level(intent_level, service_mode),
    }
    issues = _build_trace_issues(intent_level, route_debug, flow_debug, raw_data)
    trace_summary = _build_trace_summary(trace_meta, route_debug, issues)

    return {
        **prediction,
        "intent": intent,
        "sql": raw_data.get("sql", prediction.get("sql")),
        "fallback_used": bool(raw_data.get("fallback_used", prediction.get("fallback_used"))),
        "route_debug": route_debug,
        "flow_debug": flow_debug,
        "trace_meta": trace_meta,
        "issues": issues,
        "trace_summary": trace_summary,
        "sop_trace": list(raw_data.get("sop_trace") or prediction.get("sop_trace") or []),
    }
