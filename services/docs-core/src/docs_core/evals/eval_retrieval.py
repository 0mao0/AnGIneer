"""知识检索评测模块。"""
import json
import re
from typing import Any, Dict, List

from docs_core.evals.dataset_loader import load_eval_questions, load_eval_retrieval_rows
from docs_core.query.contracts import KnowledgeQueryRequest
from docs_core.query.service import knowledge_query_service


# 计算单条样本的 Recall@K。
def compute_recall_at_k(predicted_ids: List[str], gold_ids: List[str], k: int) -> float:
    gold_set = {item for item in gold_ids if item}
    if not gold_set:
        return 0.0
    predicted_topk = set(predicted_ids[:k])
    return 1.0 if gold_set & predicted_topk else 0.0


# 计算单条样本的 MRR。
def compute_mrr(predicted_ids: List[str], gold_ids: List[str]) -> float:
    gold_set = {item for item in gold_ids if item}
    if not gold_set:
        return 0.0
    for index, item_id in enumerate(predicted_ids, start=1):
        if item_id in gold_set:
            return 1.0 / index
    return 0.0


# 归一化章节路径，兼容页码尾缀、空白和大小写差异。
def normalize_section_path(value: str) -> str:
    normalized = str(value or "").replace("（", "(").replace("）", ")").strip().lower()
    normalized = re.sub(r"\s+", " ", normalized)
    parts = [re.sub(r"\s*\(\d+\)\s*$", "", part).strip() for part in normalized.split("/") if part.strip()]
    return " / ".join(parts)


# 判断预测命中的章节路径是否覆盖任一 gold 章节。
def compute_section_hit(predicted_paths: List[str], gold_paths: List[str], k: int) -> float:
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


# 计算章节路径视角下的 MRR。
def compute_section_mrr(predicted_paths: List[str], gold_paths: List[str]) -> float:
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


# 调用当前知识查询服务，获取真实预测结果。
def run_predictions(questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    predictions: Dict[str, Dict[str, Any]] = {}
    for question in questions:
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not question_id or not query:
            continue
        request = KnowledgeQueryRequest(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            mode=str(question.get("expected_route") or "auto"),
            top_k=5,
            include_debug=True,
            include_retrieved=True,
        )
        response = knowledge_query_service.query(request)
        retrieved_items = [item.model_dump(mode="json") for item in response.retrieved_items]
        predictions[question_id] = {
            "query_id": response.query_id,
            "strategy": response.strategy,
            "task_type": response.task_type,
            "retrieved_ids": [item.item_id for item in response.retrieved_items],
            "retrieved_items": retrieved_items,
            "retrieved_section_paths": [
                str(item.get("metadata", {}).get("section_path") or "")
                for item in retrieved_items
            ],
            "retrieved_doc_ids": [str(item.get("doc_id") or "") for item in retrieved_items],
            "debug": response.debug,
            "answer": response.answer,
            "confidence": response.confidence,
            "citations": [item.model_dump(mode="json") for item in response.citations],
        }
    return predictions


# 基于离线结果计算基础检索指标。
def evaluate_retrieval(
    questions: List[Dict[str, Any]],
    gold_retrieval: Dict[str, Dict[str, Any]],
    predictions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    total = 0
    evaluated_total = 0
    scored_total = 0
    empty_expected_total = 0
    recall_at_3 = 0.0
    recall_at_5 = 0.0
    mrr = 0.0
    empty_retrieval_correct = 0.0
    details: List[Dict[str, Any]] = []
    for question in questions:
        question_id = str(question.get("question_id") or "")
        if not question_id:
            continue
        total += 1
        prediction = predictions.get(question_id, {})
        predicted_ids = list(prediction.get("retrieved_ids") or [])
        predicted_section_paths = list(prediction.get("retrieved_section_paths") or [])
        predicted_doc_ids = list(prediction.get("retrieved_doc_ids") or [])
        has_gold_annotation = question_id in gold_retrieval
        gold_row = gold_retrieval.get(question_id, {})
        gold_chunk_ids = gold_row.get("gold_chunk_ids", [])
        gold_section_paths = gold_row.get("gold_section_paths", [])
        gold_doc_ids = gold_row.get("gold_doc_ids", [])
        if not has_gold_annotation:
            details.append(
                {
                    "question_id": question_id,
                    "task_type": question.get("task_type"),
                    "strategy": prediction.get("strategy"),
                    "predicted_ids": predicted_ids,
                    "predicted_doc_ids": predicted_doc_ids,
                    "predicted_section_paths": predicted_section_paths,
                    "gold_chunk_ids": [],
                    "gold_doc_ids": [],
                    "gold_section_paths": [],
                    "retrieval_evaluated": False,
                    "retrieval_expected": None,
                    "hit@3": None,
                    "hit@5": None,
                    "mrr": None,
                    "empty_retrieval_correct": None,
                    "debug": prediction.get("debug", {}),
                }
            )
            continue
        evaluated_total += 1
        retrieval_expected = bool(gold_section_paths or gold_doc_ids or gold_chunk_ids)
        if retrieval_expected:
            scored_total += 1
            recall_at_3 += compute_section_hit(predicted_section_paths, gold_section_paths, 3)
            recall_at_5 += compute_section_hit(predicted_section_paths, gold_section_paths, 5)
            mrr += compute_section_mrr(predicted_section_paths, gold_section_paths)
        else:
            empty_expected_total += 1
            empty_retrieval_correct += 1.0 if not predicted_ids else 0.0
        details.append(
            {
                "question_id": question_id,
                "task_type": question.get("task_type"),
                "strategy": prediction.get("strategy"),
                "predicted_ids": predicted_ids,
                "predicted_doc_ids": predicted_doc_ids,
                "predicted_section_paths": predicted_section_paths,
                "gold_chunk_ids": gold_chunk_ids,
                "gold_doc_ids": gold_doc_ids,
                "gold_section_paths": gold_section_paths,
                "retrieval_evaluated": True,
                "retrieval_expected": retrieval_expected,
                "hit@3": compute_section_hit(predicted_section_paths, gold_section_paths, 3) if retrieval_expected else None,
                "hit@5": compute_section_hit(predicted_section_paths, gold_section_paths, 5) if retrieval_expected else None,
                "mrr": round(compute_section_mrr(predicted_section_paths, gold_section_paths), 4) if retrieval_expected else None,
                "empty_retrieval_correct": (1.0 if not predicted_ids else 0.0) if not retrieval_expected else None,
                "debug": prediction.get("debug", {}),
            }
        )
    if total == 0:
        return {
            "total": 0,
            "evaluated_total": 0,
            "scored_total": 0,
            "empty_expected_total": 0,
            "recall@3": 0.0,
            "recall@5": 0.0,
            "mrr": 0.0,
            "empty_retrieval_correct_rate": 0.0,
            "details": [],
        }
    return {
        "total": total,
        "evaluated_total": evaluated_total,
        "scored_total": scored_total,
        "empty_expected_total": empty_expected_total,
        "recall@3": round(recall_at_3 / scored_total, 4) if scored_total else None,
        "recall@5": round(recall_at_5 / scored_total, 4) if scored_total else None,
        "mrr": round(mrr / scored_total, 4) if scored_total else None,
        "empty_retrieval_correct_rate": round(empty_retrieval_correct / empty_expected_total, 4) if empty_expected_total else None,
        "details": details,
    }


# 脚本入口：读取问题集并直接调用当前知识查询主链。
def main() -> None:
    questions = load_eval_questions()
    gold_retrieval_rows = load_eval_retrieval_rows()
    gold_retrieval = {str(row.get("question_id") or ""): row for row in gold_retrieval_rows}
    predictions = run_predictions(questions)
    report = evaluate_retrieval(questions, gold_retrieval, predictions)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
