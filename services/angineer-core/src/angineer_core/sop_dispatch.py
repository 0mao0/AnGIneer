"""L3 SOP 调度（P6d 从 dispatcher.py 下沉）。

IntentClassifier 路由 → 命中且过阈值 → SopRunner/Dispatcher 执行 →
final_context 答题组装 + trace/citations 构建。
"""
import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)


def dispatch_sop(
    dispatcher,
    query: str,
    sop_loader,
    intent_result,
    step_callback=None,
) -> Tuple[str, list, str, bool, Optional[float], list, Dict[str, Any], Dict[str, Any]]:
    """L3 路径：SOP 匹配与执行。"""
    from angineer_core.classifier import IntentClassifier
    from angineer_core.qa_pipeline import extract_answer_from_sop_context

    answer = ""
    citations = []
    strategy_desc = ""
    fallback_used = False
    sop_timing = None
    stage_timings: Dict[str, Any] = {}
    sop_trace: list = []
    route_debug: Dict[str, Any] = {
        "route_kind": "standard_sop",
        "matched_sop_id": "",
        "matched_sop_name": "",
        "confidence": None,
        "candidates": [],
        "args": {},
        "missing_args": [],
        "reason": intent_result.reason or "",
    }
    flow_debug: Dict[str, Any] = {
        "flow_type": "standard_sop",
        "sop_id": "",
        "sop_name": "",
        "generated_sop": None,
        "final_context": {},
        "summary": "",
    }

    try:
        _t_sop = time.time()
        if sop_loader is not None:
            sops = sop_loader.load_all()
            classifier = IntentClassifier(sops)
        else:
            classifier = None

        if classifier is not None:
            _t_route = time.time()
            route_result = classifier.route(
                query, config_name=dispatcher.config_name, mode=dispatcher.mode
            )
            route_timing = round(time.time() - _t_route, 2)
            matched_sop = route_result.sop
            route_debug.update({
                "matched_sop_id": matched_sop.id if matched_sop else "",
                "matched_sop_name": (
                    matched_sop.name_zh
                    or matched_sop.name_en
                    or matched_sop.id
                ) if matched_sop else "",
                "confidence": route_result.confidence,
                "candidates": route_result.candidates or [],
                "args": route_result.args or {},
                "reason": route_result.reason or "",
            })

            if route_result.sop and route_result.confidence >= SOP_ROUTE_CONFIDENCE_THRESHOLD:
                sop_full = sop_loader.analyze_sop(
                    route_result.sop.id, prefer_llm=False
                )
                required_args = list(((sop_full.blackboard or {}).get("required") or []))
                route_debug["missing_args"] = [
                    key for key in required_args if key not in (route_result.args or {})
                ]

                from angineer_core.dispatcher import Dispatcher

                sop_dispatcher = Dispatcher(
                    config_name=dispatcher.config_name, mode=dispatcher.mode
                )
                initial_context = {"user_query": query}
                initial_context.update(route_result.args)

                if step_callback:
                    try:
                        step_callback({
                            "event": "route_completed",
                            "route_debug": {
                                "route_kind": "standard_sop",
                                "matched_sop_id": sop_full.id,
                                "matched_sop_name": sop_full.name_zh or sop_full.name_en or sop_full.id,
                                "confidence": route_result.confidence,
                                "candidates": route_result.candidates or [],
                                "args": route_result.args or {},
                                "missing_args": route_debug.get("missing_args", []),
                                "reason": route_result.reason or "",
                            },
                            "intent": {"intent_level": "L3", "service_mode": "standard_sop"},
                        })
                    except Exception as e:
                        logger.warning(f"路由完成回调失败: {e}")

                _t_execute = time.time()
                final_context = sop_dispatcher.run_sop(sop_full, initial_context, step_callback=step_callback)
                execute_timing = round(time.time() - _t_execute, 2)

                _t_answer = time.time()
                answer = extract_answer_from_sop_context(
                    final_context, query
                )
                stage_timings["llm"] = round(time.time() - _t_answer, 2)
                citations = sop_dispatcher._build_citations_from_sop_trace(sop_dispatcher)
                sop_trace = sop_dispatcher._build_sop_trace(sop_dispatcher, sop_full)
                strategy_desc = (
                    f"SOP 执行 ({route_result.sop.id}, "
                    f"confidence={route_result.confidence:.2f})"
                )
                flow_debug.update({
                    "sop_id": sop_full.id,
                    "sop_name": sop_full.name_zh or sop_full.name_en or sop_full.id,
                    "final_context": final_context or {},
                    "summary": (
                        f"命中 SOP `{sop_full.id}`，执行 {len(sop_full.steps)} 个步骤。"
                    ),
                })
                sop_timing = route_timing
                stage_timings["sop_execute"] = execute_timing
            else:
                logger.info(
                    f"SOP 未匹配或置信度不足: {route_result.reason}"
                )
                flow_debug["summary"] = route_result.reason or "SOP 未匹配或置信度不足。"
                fallback_used = True
        else:
            route_debug["reason"] = "SOP Loader 不可用，无法执行标准 SOP 路径。"
            flow_debug["summary"] = route_debug["reason"]
            fallback_used = True
    except Exception as e:
        logger.warning(f"SOP 执行失败，回退语义检索: {e}")
        route_debug["reason"] = str(e)
        flow_debug["summary"] = f"SOP 执行失败: {e}"
        fallback_used = True

    return answer, citations, strategy_desc, fallback_used, sop_timing, sop_trace, route_debug, flow_debug
