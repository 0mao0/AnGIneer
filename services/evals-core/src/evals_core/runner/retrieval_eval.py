"""检索评测器，通过 query_engine 直接调用检索链路。"""
import re
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator
from evals_core.runner._prediction_trace import enrich_prediction_trace
from evals_core.runner._query_helper import run_eval_query


def normalize_section_path(value: str) -> str:
    """归一化章节路径，兼容页码尾缀、空白和大小写差异。"""
    normalized = str(value or "").replace("（", "(").replace("）", ")").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    parts = [re.sub(r"\s*\(\d+\)\s*$", "", part).strip() for part in normalized.split("/") if part.strip()]
    return " / ".join(parts)


def compute_section_hit(predicted_paths: List[str], gold_paths: List[str], k: int) -> float:
    """判断预测命中的章节路径是否覆盖任一 gold 章节。"""
    gold_normalized = [normalize_section_path(item) for item in gold_paths if normalize_section_path(item)]
    if not gold_normalized:
        return 0.0
    predicted_normalized = [
        normalize_section_path(item)
        for item in predicted_paths[:k]
        if normalize_section_path(item)
    ]
    for predicted_path in predicted_normalized:
        for gold_path in gold_normalized:
            if predicted_path == gold_path or predicted_path.endswith(gold_path) or gold_path in predicted_path:
                return 1.0
    return 0.0


def compute_section_mrr(predicted_paths: List[str], gold_paths: List[str]) -> float:
    """计算章节路径视角下的 MRR。"""
    gold_normalized = [normalize_section_path(item) for item in gold_paths if normalize_section_path(item)]
    if not gold_normalized:
        return 0.0
    for index, predicted_path in enumerate(predicted_paths, start=1):
        normalized_predicted = normalize_section_path(predicted_path)
        if not normalized_predicted:
            continue
        if any(
            normalized_predicted == gold_path or normalized_predicted.endswith(gold_path) or gold_path in normalized_predicted
            for gold_path in gold_normalized
        ):
            return 1.0 / index
    return 0.0


def compute_citation_hit(predicted_citations: List[Dict[str, Any]], gold_target_ids: List[str]) -> float:
    """判断预测 citations 是否命中任一 gold target。"""
    normalized_gold = {str(item or "").strip() for item in gold_target_ids if str(item or "").strip()}
    if not normalized_gold:
        return 0.0
    for citation in predicted_citations:
        if not isinstance(citation, dict):
            continue
        reference = citation.get("reference") if isinstance(citation.get("reference"), dict) else {}
        predicted_target_id = str(
            reference.get("targetId")
            or reference.get("target_id")
            or citation.get("target_id")
            or ""
        ).strip()
        if predicted_target_id and predicted_target_id in normalized_gold:
            return 1.0
    return 0.0


def compute_failure_bucket(
    predicted_section_paths: List[str],
    predicted_citations: List[Dict[str, Any]],
    predicted_items: List[Dict[str, Any]],
    gold: Dict[str, Any],
) -> str:
    """按失败模式输出稳定分桶。"""
    gold_target_ids = {str(item or "").strip() for item in gold.get("gold_target_ids", []) if str(item or "").strip()}
    gold_target_types = {str(item or "").strip() for item in gold.get("gold_target_types", []) if str(item or "").strip()}
    predicted_target_ids = {
        str(
            ((citation.get("reference") or {}) if isinstance(citation, dict) else {}).get("targetId")
            or ((citation.get("reference") or {}) if isinstance(citation, dict) else {}).get("target_id")
            or ""
        ).strip()
        for citation in predicted_citations
        if isinstance(citation, dict)
    }
    predicted_target_types = {
        str((item.get("metadata") or {}).get("target_type") or item.get("entity_type") or "").strip()
        for item in predicted_items
        if isinstance(item, dict)
    }
    if gold_target_ids and predicted_target_ids.intersection(gold_target_ids):
        return "ok"
    if compute_section_hit(predicted_section_paths, list(gold.get("gold_section_paths") or []), 5) > 0:
        return "wrong_section_bias"
    if "figure" in gold_target_types and "content" in predicted_target_types:
        return "caption_body_confusion"
    if "formula" in gold_target_types and "formula_param" in predicted_target_types:
        return "formula_symbol_confusion"
    return "missed_exact_target"


class RetrievalEvaluator(BaseEvaluator):
    """检索评测器，通过 query_engine 直接调用检索链路。"""

    @staticmethod
    def _emit_enriched_stage(
        question: Dict[str, Any],
        partial: Dict[str, Any],
        stage_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        """把检索链路的中间态归一化后回传给评测轮询层。"""
        if not stage_callback:
            return
        retrieved_items = list(partial.get("retrieved_items") or [])
        prediction = {
            "retrieved_ids": [item.get("item_id", "") for item in retrieved_items if isinstance(item, dict)],
            "retrieved_section_paths": [
                str(item.get("metadata", {}).get("section_path") or "")
                for item in retrieved_items if isinstance(item, dict)
            ],
            "retrieved_doc_ids": [str(item.get("doc_id") or "") for item in retrieved_items if isinstance(item, dict)],
            "retrieved_items": retrieved_items,
            "answer": partial.get("answer", ""),
            "citations": list(partial.get("citations") or []),
            "task_type": partial.get("task_type", ""),
            "strategy": partial.get("strategy", ""),
            "system_prompt": partial.get("system_prompt", ""),
            "retrieval_debug": partial.get("retrieval_debug", {}),
            "stage_timings": partial.get("stage_timings", {}),
            "intent": partial.get("intent", {}),
            "stage": partial.get("stage", ""),
        }
        stage_callback(enrich_prediction_trace(question, partial, prediction))

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """通过 query_engine 直接调用检索链路。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}

        data = run_eval_query(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            doc_ids=list(question.get("doc_ids") or []),
            session_id=f"eval-{question_id}",
            stage_callback=(lambda partial: self._emit_enriched_stage(question, partial, stage_callback)) if stage_callback else None,
        )

        if "error" in data:
            return data

        retrieved_items = list(data.get("retrieved_items") or [])
        prediction = {
            "retrieved_ids": [item.get("item_id", "") for item in retrieved_items if isinstance(item, dict)],
            "retrieved_section_paths": [
                str(item.get("metadata", {}).get("section_path") or "")
                for item in retrieved_items if isinstance(item, dict)
            ],
            "retrieved_doc_ids": [str(item.get("doc_id") or "") for item in retrieved_items if isinstance(item, dict)],
            "retrieved_items": retrieved_items,
            "answer": data.get("answer", ""),
            "citations": list(data.get("citations") or []),
            "task_type": data.get("task_type", ""),
            "strategy": data.get("strategy", ""),
            "debug": data.get("debug", {}),
            "system_prompt": data.get("system_prompt", ""),
            "retrieval_debug": data.get("retrieval_debug", {}),
            "stage_timings": data.get("stage_timings", {}),
            "intent": data.get("intent", {}),
        }
        return enrich_prediction_trace(question, data, prediction)

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算检索评测指标。"""
        predicted_section_paths = list(prediction.get("retrieved_section_paths") or [])
        gold_section_paths = list(gold.get("gold_section_paths") or [])
        gold_doc_ids = list(gold.get("gold_doc_ids") or [])
        predicted_citations = list(prediction.get("citations") or [])
        predicted_items = list(prediction.get("retrieved_items") or [])
        gold_target_ids = list(gold.get("gold_target_ids") or [])
        retrieval_expected = bool(gold_section_paths or gold_doc_ids)
        if not retrieval_expected:
            return {
                "score": None,
                "evaluated": False,
                "retrieval_expected": False,
                "note": "无检索标准，无法评测",
            }
        hit_at_3 = compute_section_hit(predicted_section_paths, gold_section_paths, 3)
        hit_at_5 = compute_section_hit(predicted_section_paths, gold_section_paths, 5)
        mrr = compute_section_mrr(predicted_section_paths, gold_section_paths)
        citation_hit = compute_citation_hit(predicted_citations, gold_target_ids)
        return {
            "score": hit_at_5,
            "evaluated": True,
            "retrieval_expected": True,
            "hit@1": compute_section_hit(predicted_section_paths, gold_section_paths, 1),
            "hit@3": hit_at_3,
            "hit@5": hit_at_5,
            "mrr": round(mrr, 4),
            "citation_hit": citation_hit,
            "question_type": str(gold.get("question_type") or ""),
            "gold_target_types": list(gold.get("gold_target_types") or []),
            "failure_bucket": compute_failure_bucket(
                predicted_section_paths,
                predicted_citations,
                predicted_items,
                gold,
            ),
        }


register_evaluator("retrieval", RetrievalEvaluator)
