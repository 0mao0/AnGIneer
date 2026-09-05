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


def _extract_predicted_doc_ids(prediction: Dict[str, Any]) -> List[str]:
    """提取预测命中的 doc_id 序列（保序去重），兼容 retrieved_items 结构。"""
    raw_ids = list(prediction.get("retrieved_doc_ids") or [])
    if not raw_ids:
        raw_ids = [
            str(item.get("doc_id") or "")
            for item in prediction.get("retrieved_items") or []
            if isinstance(item, dict)
        ]
    seen = set()
    ordered: List[str] = []
    for doc_id in raw_ids:
        normalized = str(doc_id or "").strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            ordered.append(normalized)
    return ordered


def _extract_predicted_section_paths(prediction: Dict[str, Any]) -> List[str]:
    """提取预测命中的章节路径，兼容 retrieved_items[].metadata.section_path 结构。"""
    raw_paths = list(prediction.get("retrieved_section_paths") or [])
    if not raw_paths:
        raw_paths = [
            str((item.get("metadata") or {}).get("section_path") or "")
            for item in prediction.get("retrieved_items") or []
            if isinstance(item, dict)
        ]
    return [str(path) for path in raw_paths if str(path or "").strip()]


def compute_doc_hit(predicted_doc_ids: List[str], gold_doc_ids: List[str], k: int) -> float:
    """判断 top-k 预测命中的文档是否覆盖任一 gold 文档（doc 粒度）。"""
    gold_normalized = {str(item or "").strip() for item in gold_doc_ids if str(item or "").strip()}
    if not gold_normalized:
        return 0.0
    for doc_id in list(predicted_doc_ids or [])[:k]:
        if str(doc_id or "").strip() in gold_normalized:
            return 1.0
    return 0.0


def compute_doc_mrr(predicted_doc_ids: List[str], gold_doc_ids: List[str]) -> float:
    """计算 doc 粒度下的 MRR。"""
    gold_normalized = {str(item or "").strip() for item in gold_doc_ids if str(item or "").strip()}
    if not gold_normalized:
        return 0.0
    for index, doc_id in enumerate(predicted_doc_ids or [], start=1):
        if str(doc_id or "").strip() in gold_normalized:
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
    predicted_doc_ids: Optional[List[str]] = None,
) -> str:
    """按失败模式输出稳定分桶。"""
    gold_target_ids = {str(item or "").strip() for item in gold.get("gold_target_ids", []) if str(item or "").strip()}
    hard_negative_target_ids = {
        str(item or "").strip()
        for item in gold.get("hard_negative_target_ids", [])
        if str(item or "").strip()
    }
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
    if hard_negative_target_ids and predicted_target_ids.intersection(hard_negative_target_ids):
        return "hard_negative_bias"
    gold_doc_ids = {str(item or "").strip() for item in gold.get("gold_doc_ids", []) if str(item or "").strip()}
    if gold_doc_ids and not gold_target_ids and not list(gold.get("gold_section_paths") or []):
        # 仅有 doc 粒度标注时（如 Open RAG Bench），按 doc 命中情况分桶
        top5_doc_ids = list(predicted_doc_ids or [])[:5]
        if any(doc_id in gold_doc_ids for doc_id in top5_doc_ids):
            return "ok"
        return "retrieval_miss_doc"
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
            "runtime_flags": list(partial.get("runtime_flags") or []),
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
            "runtime_flags": list(data.get("runtime_flags") or []),
        }
        return enrich_prediction_trace(question, data, prediction)

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算检索评测指标（section 粒度 + doc 粒度）。"""
        predicted_section_paths = _extract_predicted_section_paths(prediction)
        predicted_doc_ids = _extract_predicted_doc_ids(prediction)
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
        has_section_gold = bool(gold_section_paths)
        has_target_gold = bool(gold_target_ids)
        # 无标注时输出 None（语义=N/A，报告渲染为 —），而不是 0.0 伪装成"命中率为零"
        hit_at_1 = compute_section_hit(predicted_section_paths, gold_section_paths, 1) if has_section_gold else None
        hit_at_3 = compute_section_hit(predicted_section_paths, gold_section_paths, 3) if has_section_gold else None
        hit_at_5 = compute_section_hit(predicted_section_paths, gold_section_paths, 5) if has_section_gold else None
        mrr = compute_section_mrr(predicted_section_paths, gold_section_paths) if has_section_gold else None
        hit_at_1_doc = compute_doc_hit(predicted_doc_ids, gold_doc_ids, 1)
        hit_at_3_doc = compute_doc_hit(predicted_doc_ids, gold_doc_ids, 3)
        hit_at_5_doc = compute_doc_hit(predicted_doc_ids, gold_doc_ids, 5)
        mrr_doc = compute_doc_mrr(predicted_doc_ids, gold_doc_ids)
        citation_hit = compute_citation_hit(predicted_citations, gold_target_ids) if has_target_gold else None
        # 主分数：有 section 标注用 section 粒度，否则降级到 doc 粒度
        effective_hit5 = hit_at_5 if has_section_gold else hit_at_5_doc
        return {
            "score": effective_hit5,
            "evaluated": True,
            "retrieval_expected": True,
            "metric_granularity": "section" if has_section_gold else "doc",
            "hit@1": hit_at_1,
            "hit@3": hit_at_3,
            "hit@5": hit_at_5,
            "mrr": round(mrr, 4) if mrr is not None else None,
            "hit@1_doc": hit_at_1_doc,
            "hit@3_doc": hit_at_3_doc,
            "hit@5_doc": hit_at_5_doc,
            "mrr_doc": round(mrr_doc, 4),
            "citation_hit": citation_hit,
            "question_type": str(gold.get("question_type") or ""),
            "gold_target_types": list(gold.get("gold_target_types") or []),
            "failure_bucket": compute_failure_bucket(
                predicted_section_paths,
                predicted_citations,
                predicted_items,
                gold,
                predicted_doc_ids=predicted_doc_ids,
            ),
        }


register_evaluator("retrieval", RetrievalEvaluator)
