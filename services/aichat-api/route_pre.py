"""Router 前置（阶段 1b）：请求先过 route_request 拿派工单 RouteDecision，再进执行。

硬规则：意图可以错，scope 不能漏；分类失败不再 intent_result=None 静默，
而是 RouteDecision.fallback=True + route_debug.fallback=true，由 SSE 首帧透出。
"""
import logging
import os
from typing import Any, Awaitable, Callable, List, Optional

from angineer_core.agent_events import AgentEvent
from angineer_core.base_contracts import RouteDebug, RouteDecision, ScopeContext

logger = logging.getLogger(__name__)

ROUTE_PRE_ENV = "ANGINEER_ROUTE_PRE"

ClassifyFn = Callable[[str, Optional[str], str], Awaitable[Any]]


def route_pre_enabled() -> bool:
    """ANGINEER_ROUTE_PRE=false 时回退旧内联分类路径（无 route_debug 首帧）。"""
    return os.getenv(ROUTE_PRE_ENV, "true").strip().lower() in ("true", "1", "yes", "on")


async def route_request(
    *,
    query: str,
    scene: str,
    library_id: Optional[str],
    doc_ids: Optional[List[str]],
    config_name: Optional[str],
    mode: str,
    classify: ClassifyFn,
) -> RouteDecision:
    """生成本次请求的派工单；分类失败 -> fallback 决策（scope 仍显式保留）。"""
    scope = ScopeContext(library_id=library_id or "default", doc_ids=list(doc_ids or []))
    intent_result = await classify(query, config_name, mode)
    if intent_result is None:
        return RouteDecision(
            scene=scene,
            scope=scope,
            fallback=True,
            route_debug=RouteDebug(fallback=True, reason="classifier_error"),
        )
    return RouteDecision(
        intent_result=intent_result,
        scene=scene,
        scope=scope,
        attempts=[str(m) for m in (intent_result.execution_plan or [])],
        route_debug=RouteDebug(
            level=intent_result.primary_level or intent_result.intent_level,
            service_mode=intent_result.service_mode,
            reason=intent_result.reason,
        ),
    )


def decision_intent_result(decision: RouteDecision):
    """fallback 决策沿用旧降级路径（intent_result=None -> 默认策略），行为不变。"""
    return None if decision.fallback else decision.intent_result


def route_debug_event(decision: RouteDecision) -> AgentEvent:
    """SSE 首帧：级别 / service_mode / confidence / reason / fallback + scope。"""
    return AgentEvent(
        type="route_debug",
        run_id="",
        payload={
            "route_debug": decision.route_debug.model_dump(),
            "scope": decision.scope.model_dump(),
            "attempts": list(decision.attempts),
        },
    )


def fallback_note_event() -> AgentEvent:
    """分类异常时前端可感知的说明帧。"""
    return AgentEvent(type="note", run_id="", payload={"detail": "路由失败，按默认策略走"})
