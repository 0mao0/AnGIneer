"""SOP 执行评测器，通过 query_engine 直接调用 L3 SOP 链路。"""
from typing import Any, Callable, Dict, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator
from evals_core.runner._prediction_trace import enrich_prediction_trace
from evals_core.runner._query_helper import run_eval_query
from evals_core.runner.answer_eval import (
    DEFAULT_SEMANTIC_THRESHOLD,
    _llm_semantic_evaluate,
    _build_gold_answer,
    is_refusal,
)


class SopEvaluator(BaseEvaluator):
    """SOP 执行评测器，通过 query_engine 直接调用 L3 SOP 链路。"""

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """通过 query_engine 直接调用 L3 SOP 执行链路。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}

        if stage_callback:
            stage_callback({
                "answer": "",
                "stage": "intent",
                "stage_timings": {},
                "sop_trace": [],
                "intent": {"intent_level": "", "service_mode": ""},
            })

        partial_sop_trace = []
        route_context = {}

        def _enrich_partial(partial: Dict[str, Any]) -> Dict[str, Any]:
            """对中间结果进行 trace enrichment，确保前端能正确解析。"""
            intent = partial.get("intent", {})
            route_debug = partial.get("route_debug", {})
            if not route_debug and not intent:
                return partial

            intent_level = str(intent.get("intent_level", "L1"))
            service_mode = str(intent.get("service_mode", ""))
            trace_meta = {
                "level": intent_level,
                "trace_mode": "standard_sop" if intent_level in ("L3", "L4") else "direct",
                "service_mode": service_mode,
                "title": f"标准 SOP 执行 ({service_mode})" if service_mode else "流程执行",
            }
            flow_debug = {
                "strategy": f"SOP 执行 ({route_debug.get('matched_sop_id', '')})",
                "summary": f"执行中... 已完成 {len(partial.get('sop_trace', []))} 个步骤",
            }

            return {
                **partial,
                "intent": {
                    **intent,
                    "primary_level": intent.get("primary_level", intent.get("intent_level", "")),
                    "execution_plan": list(intent.get("execution_plan") or [intent.get("service_mode", "")] if intent.get("service_mode") else []),
                },
                "route_debug": route_debug,
                "flow_debug": flow_debug,
                "trace_meta": trace_meta,
                "issues": [],
                "trace_summary": "",
            }

        def _on_step_complete(step_info: Dict[str, Any]):
            """每个 SOP 步骤完成时的回调，实时推送部分结果给前端。"""
            nonlocal partial_sop_trace

            if isinstance(step_info, dict) and step_info.get("event") == "route_completed":
                route_context["route_debug"] = step_info.get("route_debug", {})
                route_context["intent"] = step_info.get("intent", {})
                if stage_callback:
                    partial_result = {
                        "answer": "",
                        "stage": "route_completed",
                        "stage_timings": {},
                        "sop_trace": [],
                        **route_context,
                    }
                    enriched = _enrich_partial(partial_result)
                    stage_callback(enriched)
                return

            partial_sop_trace.append(step_info)
            if stage_callback:
                partial_result = {
                    "answer": "",
                    "stage": "sop_executing",
                    "stage_timings": {},
                    "sop_trace": list(partial_sop_trace),
                }
                if route_context:
                    partial_result.update(route_context)

                enriched = _enrich_partial(partial_result)
                stage_callback(enriched)

        data = run_eval_query(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            doc_ids=list(question.get("doc_ids") or []),
            session_id=f"eval-sop-{question_id}",
            step_callback=_on_step_complete if stage_callback else None,
        )

        if "error" in data:
            return {"error": data["error"]}

        result = {
            "answer": data.get("answer", ""),
            "citations": list(data.get("citations") or []),
            "confidence": data.get("confidence", 0.0),
            "retrieved_items": list(data.get("retrieved_items") or []),
            "task_type": data.get("intent", {}).get("intent_type", ""),
            "strategy": data.get("strategy", ""),
            "debug": data.get("debug", {}),
            "thinking": data.get("queryChain", ""),
            "system_prompt": data.get("system_prompt", ""),
            "retrieval_debug": data.get("retrieval_debug", {}),
            "stage_timings": data.get("stage_timings", {}),
            "intent": data.get("intent", {}),
            "sop_trace": data.get("sop_trace", []),
        }

        result = enrich_prediction_trace(question, data, result)

        if stage_callback:
            stage_callback(result)

        return result

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """SOP 评测评估：L3 级题目仅使用 LLM 语义评判，不做关键词校验。"""
        answer = str(prediction.get("answer") or "").strip()
        gold_answer = str(gold.get("gold_answer") or "").strip()
        semantic_threshold = DEFAULT_SEMANTIC_THRESHOLD

        intent = prediction.get("intent") or {}
        strategy = str(prediction.get("strategy") or "")
        sop_matched = strategy.startswith("SOP 执行")

        if not answer:
            return {
                "score": 0.0,
                "evaluated": True,
                "has_answer": False,
                "sop_matched": sop_matched,
                "intent_level": intent.get("intent_level", ""),
            }

        semantic_result = _llm_semantic_evaluate(answer, gold_answer, [], semantic_threshold)

        # 步骤执行验证：统计成功/失败/跳过，对过度跳过施加惩罚
        sop_trace = prediction.get("sop_trace") or []
        successful_steps = 0
        failed_steps = 0
        skipped_steps = 0
        for s in sop_trace:
            status = str(s.get("status") or "").lower()
            outputs = s.get("outputs")
            if status in ("error", "failed"):
                failed_steps += 1
            elif status == "skipped" or (isinstance(outputs, dict) and outputs.get("skipped")):
                skipped_steps += 1
            elif status == "success":
                successful_steps += 1

        total_steps = len(sop_trace)
        step_bypass_ratio = skipped_steps / max(total_steps, 1)
        step_penalty = 1.0
        if step_bypass_ratio > 0.5:
            step_penalty = max(0.5, 1.0 - (step_bypass_ratio - 0.5))
        elif total_steps > 0 and successful_steps == 0 and failed_steps > 0:
            step_penalty = 0.3

        step_execution_detail = {
            "total_steps": total_steps,
            "successful": successful_steps,
            "failed": failed_steps,
            "skipped": skipped_steps,
            "bypass_ratio": round(step_bypass_ratio, 2),
            "penalty_applied": step_penalty < 1.0,
        }

        if semantic_result["semantic_evaluated"]:
            correctness_score = semantic_result["semantic_score"]
            overall_score = (1.0 if semantic_result["semantic_passed"] else 0.0) * step_penalty
        else:
            correctness_score = 0.0
            overall_score = 0.0

        return {
            "score": overall_score,
            "evaluated": True,
            "has_answer": True,
            "sop_matched": sop_matched,
            "intent_level": intent.get("intent_level", ""),
            "correctness_checked": False,
            "correctness_score": correctness_score,
            "check_details": [],
            "semantic_score": semantic_result["semantic_score"],
            "semantic_reason": semantic_result["semantic_reason"],
            "semantic_evaluated": semantic_result["semantic_evaluated"],
            "semantic_fallback": semantic_result["semantic_fallback"],
            "semantic_passed": semantic_result["semantic_passed"],
            "semantic_threshold": semantic_threshold,
            "step_execution": step_execution_detail,
        }


register_evaluator("sop", SopEvaluator)
