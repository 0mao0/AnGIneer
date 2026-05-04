"""知识回答评测模块。"""
import json
import math
from typing import Any, Dict, List

import httpx

from docs_core.evals.dataset_loader import load_eval_answer_rows, load_eval_questions
from docs_core.evals.eval_retrieval import normalize_section_path

API_BASE = "http://localhost:8789"


# 通过 /api/query 端点调用新链路，获取回答结果。
def run_predictions(questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    predictions: Dict[str, Dict[str, Any]] = {}
    with httpx.Client(timeout=60.0) as client:
        for question in questions:
            question_id = str(question.get("question_id") or "")
            query = str(question.get("question") or "").strip()
            if not question_id or not query:
                continue
            try:
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
                print(f"[eval] query failed for {question_id}: {exc}")
                data = {}
            predictions[question_id] = {
                "query_id": data.get("query_id", ""),
                "strategy": (data.get("intent") or {}).get("service_mode", ""),
                "task_type": (data.get("intent") or {}).get("intent_level", ""),
                "answer": data.get("answer", ""),
                "confidence": data.get("confidence", 0.0),
                "citations": list(data.get("citations") or []),
                "retrieved_items": list(data.get("retrieved_items") or []),
                "debug": data.get("debug", {}),
            }
    return predictions


# 归一化评测文本，便于做关键词断言。
def normalize_eval_text(value: str) -> str:
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


# 判断答案是否满足单条结构化正确性断言。
def evaluate_correctness_check(answer: str, check: Dict[str, Any]) -> bool:
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


# 计算两个已归一化向量的余弦相似度。
def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(l_value * r_value for l_value, r_value in zip(left, right)))


# 基于 embedding 计算答案与标准答案的语义相似度，用于兜底校验关键词匹配。
def _compute_semantic_similarity(answer: str, gold_answer: str) -> float:
    answer_text = str(answer or "").strip()
    gold_text = str(gold_answer or "").strip()
    if not answer_text or not gold_text:
        return 0.0
    try:
        from docs_core.indexing.embedding_provider import default_embedding_provider
        embeddings = default_embedding_provider.embed_texts([answer_text, gold_text])
        if len(embeddings) != 2:
            return 0.0
        return _cosine_similarity(embeddings[0], embeddings[1])
    except Exception:
        return 0.0


# 基于 gold 中的结构化断言判断回答是否正确。
def evaluate_answer_correctness(answer: str, gold: Dict[str, Any]) -> Dict[str, Any]:
    checks = [item for item in gold.get("correctness_checks", []) if isinstance(item, dict)]
    if not checks:
        return {
            "checked": False,
            "score": None,
            "failed_checks": [],
        }
    failed_checks = [check for check in checks if not evaluate_correctness_check(answer, check)]
    semantic_threshold = float(gold.get("semantic_threshold", 0.55))
    if not failed_checks and semantic_threshold > 0:
        gold_answer = str(gold.get("gold_answer") or gold.get("gold_answer_text") or "").strip()
        if gold_answer:
            similarity = _compute_semantic_similarity(answer, gold_answer)
            if similarity < semantic_threshold:
                failed_checks.append({
                    "type": "semantic_similarity",
                    "keywords": [f"语义相似度 {similarity:.2f} < 阈值 {semantic_threshold}"],
                    "similarity": similarity,
                    "threshold": semantic_threshold,
                })
    return {
        "checked": True,
        "score": 1.0 if not failed_checks else 0.0,
        "failed_checks": failed_checks,
    }


# 判断回答是否触发系统默认拒答。
def is_refusal(answer: str) -> bool:
    normalized = (answer or "").strip()
    refusal_markers = (
        "没有检索到足够证据",
        "建议缩小文档范围",
        "换一种问法",
    )
    return any(marker in normalized for marker in refusal_markers)


# 判断引用中是否覆盖 gold 的章节路径要求。
def citations_match_section_paths(citations: List[Dict[str, Any]], gold_section_paths: List[str]) -> bool:
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


# 评估回答质量的最小闭环。
def evaluate_answers(
    questions: List[Dict[str, Any]],
    gold_answers: Dict[str, Dict[str, Any]],
    predictions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    total = 0
    answer_non_empty = 0.0
    citation_hit = 0.0
    refusal_correct = 0.0
    correctness_total = 0
    correctness_hit = 0.0
    details: List[Dict[str, Any]] = []
    for question in questions:
        question_id = str(question.get("question_id") or "")
        if not question_id:
            continue
        total += 1
        gold = gold_answers.get(question_id, {})
        prediction = predictions.get(question_id, {})
        answer = str(prediction.get("answer") or "").strip()
        citations = list(prediction.get("citations") or [])
        predicted_target_ids = [str(item.get("target_id") or "") for item in citations]
        must_cite_target_ids = [str(item) for item in gold.get("must_cite_target_ids", []) if item]
        must_cite_section_paths = [str(item) for item in gold.get("must_cite_section_paths", []) if item]
        if not must_cite_section_paths:
            must_cite_section_paths = [str(item) for item in gold.get("gold_section_paths", []) if item]
        refusal_expected = bool(gold.get("refusal_expected", False))
        actual_refusal = is_refusal(answer)
        has_answer = 1.0 if answer else 0.0
        citation_by_target = bool(must_cite_target_ids) and bool(set(must_cite_target_ids) & set(predicted_target_ids))
        citation_by_section = citations_match_section_paths(citations, must_cite_section_paths)
        citation_ok = 1.0 if ((not must_cite_target_ids and not must_cite_section_paths) or citation_by_target or citation_by_section) else 0.0
        refusal_ok = 1.0 if refusal_expected == actual_refusal else 0.0
        correctness = evaluate_answer_correctness(answer, gold)
        answer_non_empty += has_answer
        citation_hit += citation_ok
        refusal_correct += refusal_ok
        if correctness["checked"]:
            correctness_total += 1
            correctness_hit += float(correctness["score"] or 0.0)
        details.append(
            {
                "question_id": question_id,
                "task_type": question.get("task_type"),
                "strategy": prediction.get("strategy"),
                "answer_non_empty": has_answer,
                "citation_hit": citation_ok,
                "refusal_expected": refusal_expected,
                "actual_refusal": actual_refusal,
                "refusal_correct": refusal_ok,
                "answer_correct_checked": correctness["checked"],
                "answer_correct": correctness["score"],
                "failed_correctness_checks": correctness["failed_checks"],
                "citations": citations,
                "predicted_target_ids": predicted_target_ids,
                "must_cite_target_ids": must_cite_target_ids,
                "must_cite_section_paths": must_cite_section_paths,
                "answer": answer,
                "debug": prediction.get("debug", {}),
            }
        )
    if total == 0:
        return {
            "total": 0,
            "answer_non_empty_rate": 0.0,
            "citation_hit_rate": 0.0,
            "refusal_correct_rate": 0.0,
            "correctness_checked_total": 0,
            "answer_correctness_rate": 0.0,
            "details": [],
        }
    return {
        "total": total,
        "answer_non_empty_rate": round(answer_non_empty / total, 4),
        "citation_hit_rate": round(citation_hit / total, 4),
        "refusal_correct_rate": round(refusal_correct / total, 4),
        "correctness_checked_total": correctness_total,
        "answer_correctness_rate": round(correctness_hit / correctness_total, 4) if correctness_total else 0.0,
        "details": details,
    }


# 脚本入口：读取问题集与 gold answer，并调用 /api/query 端点。
def main() -> None:
    questions = load_eval_questions()
    gold_answer_rows = load_eval_answer_rows()
    gold_answers = {str(row.get("question_id") or ""): row for row in gold_answer_rows}
    predictions = run_predictions(questions)
    report = evaluate_answers(questions, gold_answers, predictions)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
