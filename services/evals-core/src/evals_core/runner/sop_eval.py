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
            stage_callback({"answer": "", "stage": "intent", "stage_timings": {}, "sop_trace": []})

        data = run_eval_query(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            doc_ids=list(question.get("doc_ids") or []),
            session_id=f"eval-sop-{question_id}",
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

        if semantic_result["semantic_evaluated"]:
            correctness_score = semantic_result["semantic_score"]
            overall_score = 1.0 if semantic_result["semantic_passed"] else 0.0
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
        }


register_evaluator("sop", SopEvaluator)
