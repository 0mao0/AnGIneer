"""知识回答评测脚本。"""
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


# 调用当前知识查询服务，获取真实回答结果。
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
            "answer": response.answer,
            "confidence": response.confidence,
            "citations": [item.model_dump(mode="json") for item in response.citations],
            "debug": response.debug,
        }
    return predictions


# 判断回答是否触发系统默认拒答。
def is_refusal(answer: str) -> bool:
    normalized = (answer or "").strip()
    refusal_markers = (
        "没有检索到足够证据",
        "建议缩小文档范围",
        "换一种问法",
    )
    return any(marker in normalized for marker in refusal_markers)


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
        refusal_expected = bool(gold.get("refusal_expected", False))
        actual_refusal = is_refusal(answer)

        has_answer = 1.0 if answer else 0.0
        citation_ok = 1.0 if (not must_cite_target_ids or set(must_cite_target_ids) & set(predicted_target_ids)) else 0.0
        refusal_ok = 1.0 if refusal_expected == actual_refusal else 0.0

        answer_non_empty += has_answer
        citation_hit += citation_ok
        refusal_correct += refusal_ok

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
                "predicted_target_ids": predicted_target_ids,
                "must_cite_target_ids": must_cite_target_ids,
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
            "details": [],
        }

    return {
        "total": total,
        "answer_non_empty_rate": round(answer_non_empty / total, 4),
        "citation_hit_rate": round(citation_hit / total, 4),
        "refusal_correct_rate": round(refusal_correct / total, 4),
        "details": details,
    }


# 脚本入口：读取问题集与 gold answer，并调用当前知识查询主链。
def main() -> None:
    base_dir = Path(__file__).resolve().parent
    questions = load_jsonl(base_dir / "questions.jsonl")
    gold_answer_rows = load_jsonl(base_dir / "gold_answers.jsonl")
    gold_answers = {str(row.get("question_id") or ""): row for row in gold_answer_rows}
    predictions = run_predictions(questions)

    report = evaluate_answers(questions, gold_answers, predictions)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
