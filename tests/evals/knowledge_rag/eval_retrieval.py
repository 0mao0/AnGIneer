"""知识检索评测脚本。"""
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DOCS_CORE_SRC = PROJECT_ROOT / "services" / "docs-core" / "src"
API_SERVER_DIR = PROJECT_ROOT / "apps" / "api-server"

sys.path.insert(0, str(DOCS_CORE_SRC))
sys.path.insert(0, str(API_SERVER_DIR))

from docs_core.retrieval.contracts import KnowledgeQueryRequest
from docs_core.retrieval.service import knowledge_query_service


# 读取 jsonl 文件中的全部记录。
def load_jsonl(file_path: Path) -> List[Dict[str, Any]]:
    if not file_path.exists():
        return []
    records: List[Dict[str, Any]] = []
    with open(file_path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))
    return records


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
            doc_ids=list(question.get("doc_ids") or []),
            mode=str(question.get("expected_route") or "auto"),
            top_k=5,
            include_debug=True,
            include_retrieved=True,
        )
        response = knowledge_query_service.query(request)
        predictions[question_id] = {
            "query_id": response.query_id,
            "strategy": response.strategy,
            "task_type": response.task_type,
            "retrieved_ids": [item.item_id for item in response.retrieved_items],
            "retrieved_items": [item.model_dump(mode="json") for item in response.retrieved_items],
            "debug": response.debug,
            "answer": response.answer,
            "confidence": response.confidence,
        }
    return predictions


# 基于离线结果计算基础检索指标。
def evaluate_retrieval(
    questions: List[Dict[str, Any]],
    gold_retrieval: Dict[str, Dict[str, Any]],
    predictions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    total = 0
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
        gold_chunk_ids = gold_retrieval.get(question_id, {}).get("gold_chunk_ids", [])
        retrieval_expected = bool(gold_chunk_ids)
        if retrieval_expected:
            scored_total += 1
            recall_at_3 += compute_recall_at_k(predicted_ids, gold_chunk_ids, 3)
            recall_at_5 += compute_recall_at_k(predicted_ids, gold_chunk_ids, 5)
            mrr += compute_mrr(predicted_ids, gold_chunk_ids)
        else:
            empty_expected_total += 1
            empty_retrieval_correct += 1.0 if not predicted_ids else 0.0
        details.append(
            {
                "question_id": question_id,
                "task_type": question.get("task_type"),
                "strategy": prediction.get("strategy"),
                "predicted_ids": predicted_ids,
                "gold_chunk_ids": gold_chunk_ids,
                "retrieval_expected": retrieval_expected,
                "hit@3": compute_recall_at_k(predicted_ids, gold_chunk_ids, 3) if retrieval_expected else None,
                "hit@5": compute_recall_at_k(predicted_ids, gold_chunk_ids, 5) if retrieval_expected else None,
                "mrr": round(compute_mrr(predicted_ids, gold_chunk_ids), 4) if retrieval_expected else None,
                "empty_retrieval_correct": (1.0 if not predicted_ids else 0.0) if not retrieval_expected else None,
                "debug": prediction.get("debug", {}),
            }
        )

    if total == 0:
        return {
            "total": 0,
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
        "scored_total": scored_total,
        "empty_expected_total": empty_expected_total,
        "recall@3": round(recall_at_3 / scored_total, 4) if scored_total else 0.0,
        "recall@5": round(recall_at_5 / scored_total, 4) if scored_total else 0.0,
        "mrr": round(mrr / scored_total, 4) if scored_total else 0.0,
        "empty_retrieval_correct_rate": round(empty_retrieval_correct / empty_expected_total, 4) if empty_expected_total else 0.0,
        "details": details,
    }


# 脚本入口：读取问题集并直接调用当前知识查询主链。
def main() -> None:
    base_dir = Path(__file__).resolve().parent
    questions = load_jsonl(base_dir / "questions.jsonl")
    gold_retrieval_rows = load_jsonl(base_dir / "gold_retrieval.jsonl")
    gold_retrieval = {str(row.get("question_id") or ""): row for row in gold_retrieval_rows}
    predictions = run_predictions(questions)

    report = evaluate_retrieval(questions, gold_retrieval, predictions)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
