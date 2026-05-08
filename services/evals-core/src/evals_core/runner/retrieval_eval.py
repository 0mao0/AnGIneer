"""检索评测器。"""
import re
from typing import Any, Dict, List

import httpx

from evals_core.runner.base import BaseEvaluator, register_evaluator

API_BASE = "http://localhost:8789"


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


class RetrievalEvaluator(BaseEvaluator):
    """检索评测器，通过 /api/query 调用检索链路。"""

    def run_prediction(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """通过 /api/query 端点调用检索链路。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}
        try:
            with httpx.Client(timeout=180.0) as client:
                resp = client.post(f"{API_BASE}/api/query", json={
                    "query": query,
                    "library_id": str(question.get("library_id") or "default"),
                    "doc_ids": list(question.get("doc_ids") or []),
                    "scene": "docs",
                    "session_id": f"eval-{question_id}",
                })
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            return {"error": str(exc)}
        retrieved_items = list(data.get("retrieved_items") or [])
        return {
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
        }

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算检索评测指标。"""
        predicted_section_paths = list(prediction.get("retrieved_section_paths") or [])
        predicted_ids = list(prediction.get("retrieved_ids") or [])
        gold_section_paths = list(gold.get("gold_section_paths") or [])
        gold_doc_ids = list(gold.get("gold_doc_ids") or [])
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
        return {
            "score": hit_at_5,
            "evaluated": True,
            "retrieval_expected": True,
            "hit@3": hit_at_3,
            "hit@5": hit_at_5,
            "mrr": round(mrr, 4),
        }


register_evaluator("retrieval", RetrievalEvaluator)
