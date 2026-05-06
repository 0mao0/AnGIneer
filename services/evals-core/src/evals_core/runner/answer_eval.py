"""回答评测器。"""
import json
from typing import Any, Dict, List

import httpx

from evals_core.runner.base import BaseEvaluator, register_evaluator
from evals_core.runner.retrieval_eval import normalize_section_path

API_BASE = "http://localhost:8789"


def normalize_eval_text(value: str) -> str:
    """归一化评测文本，便于做关键词断言。"""
    normalized = str(value or "")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("，", ",").replace("。", ".").replace("：", ":")
    normalized = normalized.replace("；", ";").replace("～", "~").replace("％", "%")
    normalized = normalized.lower()
    compact_chars: List[str] = []
    for char in normalized:
        if char.isspace():
            continue
        if char.isalnum() or "\u4e00" <= char <= "\u9fff" or char in {".", "%", "~", "=", "+", "-", "<", ">", "(", ")", ":", "/"}:
            compact_chars.append(char)
    return "".join(compact_chars)


def evaluate_correctness_check(answer: str, check: Dict[str, Any]) -> bool:
    """判断答案是否满足单条结构化正确性断言。"""
    check_type = str(check.get("type") or "").strip()
    keywords = [normalize_eval_text(str(item)) for item in check.get("keywords", []) if str(item).strip()]
    normalized_answer = normalize_eval_text(answer)
    if not check_type or not keywords:
        return True
    if check_type == "contains_all":
        return all(keyword in normalized_answer for keyword in keywords)
    if check_type == "contains_any":
        return any(keyword in normalized_answer for keyword in keywords)
    return True


def is_refusal(answer: str) -> bool:
    """判断回答是否触发系统默认拒答。"""
    normalized = (answer or "").strip()
    refusal_markers = (
        "没有检索到足够证据",
        "建议缩小文档范围",
        "换一种问法",
    )
    return any(marker in normalized for marker in refusal_markers)


def citations_match_section_paths(citations: List[Dict[str, Any]], gold_section_paths: List[str]) -> bool:
    """判断引用中是否覆盖 gold 的章节路径要求。"""
    normalized_gold_paths = [normalize_section_path(item) for item in gold_section_paths if normalize_section_path(item)]
    if not normalized_gold_paths:
        return True
    normalized_citation_paths = [
        normalize_section_path(str(item.get("section_path") or ""))
        for item in citations
        if normalize_section_path(str(item.get("section_path") or ""))
    ]
    for citation_path in normalized_citation_paths:
        if any(
            citation_path == gold_path or citation_path.endswith(gold_path) or gold_path in citation_path
            for gold_path in normalized_gold_paths
        ):
            return True
    return False


class AnswerEvaluator(BaseEvaluator):
    """回答评测器，通过 /api/query 调用回答链路。"""

    def run_prediction(self, question: Dict[str, Any]) -> Dict[str, Any]:
        """通过 /api/query 端点调用回答链路。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}
        try:
            with httpx.Client(timeout=60.0) as client:
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
        return {
            "answer": data.get("answer", ""),
            "citations": list(data.get("citations") or []),
            "confidence": data.get("confidence", 0.0),
            "retrieved_items": list(data.get("retrieved_items") or []),
            "task_type": data.get("task_type", ""),
            "strategy": data.get("strategy", ""),
            "debug": data.get("debug", {}),
            "thinking": data.get("queryChain", ""),
        }

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算回答评测指标。"""
        answer = str(prediction.get("answer") or "").strip()
        citations = list(prediction.get("citations") or [])
        checks = [item for item in gold.get("correctness_checks", []) if isinstance(item, dict)]
        must_cite_section_paths = [str(item) for item in gold.get("must_cite_section_paths", []) if item]
        if not must_cite_section_paths:
            must_cite_section_paths = [str(item) for item in gold.get("gold_section_paths", []) if item]
        refusal_expected = bool(gold.get("refusal_expected", False))
        actual_refusal = is_refusal(answer)
        citation_ok = citations_match_section_paths(citations, must_cite_section_paths) if must_cite_section_paths else True
        if not answer:
            return {
                "score": 0.0,
                "evaluated": True,
                "has_answer": False,
                "citation_ok": citation_ok,
                "refusal_correct": refusal_expected == actual_refusal,
                "correctness_checked": False,
            }
        if not checks:
            if refusal_expected and not actual_refusal:
                score = 0.0
            elif refusal_expected and actual_refusal:
                score = 1.0
            elif not citation_ok:
                score = 0.0
            else:
                score = 1.0
            return {
                "score": score,
                "evaluated": True,
                "has_answer": True,
                "citation_ok": citation_ok,
                "refusal_correct": refusal_expected == actual_refusal,
                "correctness_checked": False,
            }
        failed_checks = [check for check in checks if not evaluate_correctness_check(answer, check)]
        correctness_score = 1.0 if not failed_checks else 0.0
        overall_score = correctness_score
        return {
            "score": overall_score,
            "evaluated": True,
            "has_answer": True,
            "citation_ok": citation_ok,
            "refusal_correct": refusal_expected == actual_refusal,
            "correctness_checked": True,
            "correctness_score": correctness_score,
            "failed_checks": failed_checks,
            "check_details": [
                {
                    "type": check.get("type"),
                    "keywords": check.get("keywords", []),
                    "passed": evaluate_correctness_check(answer, check),
                }
                for check in checks
            ],
        }


register_evaluator("answer", AnswerEvaluator)
