"""Text-to-SQL 评测模块。"""
import json
from typing import Any, Dict, List

import httpx

from docs_core.evals.dataset_loader import load_eval_questions, load_eval_sql_rows

API_BASE = "http://localhost:8789"


# 通过 /api/query 端点调用新链路，获取 SQL 结果。
def run_predictions(sql_questions: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    predictions: Dict[str, Dict[str, Any]] = {}
    with httpx.Client(timeout=60.0) as client:
        for question in sql_questions:
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
                    "session_id": f"eval-sql-{question_id}",
                })
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                print(f"[eval] query failed for {question_id}: {exc}")
                data = {}
            sql_data = data.get("sql")
            predictions[question_id] = {
                "query_id": data.get("query_id", ""),
                "task_type": (data.get("intent") or {}).get("intent_level", ""),
                "sql": sql_data,
                "answer": data.get("answer", ""),
                "debug": data.get("debug", {}),
            }
    return predictions


# 评估最小 Text-to-SQL 闭环是否返回成功执行结果。
def evaluate_text2sql(
    sql_questions: List[Dict[str, Any]],
    gold_sql: Dict[str, Dict[str, Any]],
    predictions: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    total = 0
    sql_success = 0.0
    sql_match = 0.0
    details: List[Dict[str, Any]] = []
    for question in sql_questions:
        question_id = str(question.get("question_id") or "")
        if not question_id:
            continue
        total += 1
        prediction = predictions.get(question_id, {})
        payload = dict(prediction.get("sql") or {})
        generated_sql = str(payload.get("generated_sql") or "").strip()
        execution_status = str(payload.get("execution_status") or "")
        gold_row = gold_sql.get(question_id, {})
        expected_sql = str(gold_row.get("expected_sql") or "").strip()
        success = 1.0 if execution_status == "success" else 0.0
        match = 1.0 if expected_sql and generated_sql == expected_sql else 0.0
        sql_success += success
        sql_match += match
        details.append(
            {
                "question_id": question_id,
                "task_type": prediction.get("task_type"),
                "execution_status": execution_status,
                "generated_sql": generated_sql,
                "expected_sql": expected_sql,
                "sql_success": success,
                "sql_exact_match": match if expected_sql else None,
                "debug": prediction.get("debug", {}),
            }
        )
    if total == 0:
        return {
            "total": 0,
            "sql_success_rate": 0.0,
            "sql_exact_match_rate": 0.0,
            "details": [],
        }
    exact_match_total = sum(1 for row in gold_sql.values() if row.get("expected_sql"))
    return {
        "total": total,
        "sql_success_rate": round(sql_success / total, 4),
        "sql_exact_match_rate": round(sql_match / exact_match_total, 4) if exact_match_total else 0.0,
        "details": details,
    }


# 脚本入口：读取 SQL 样本并调用 /api/query 端点。
def main() -> None:
    questions = load_eval_questions()
    gold_sql_rows = load_eval_sql_rows()
    gold_sql = {str(row.get("question_id") or ""): row for row in gold_sql_rows if row.get("question_id")}
    sql_question_ids = set(gold_sql.keys())
    sql_questions = [question for question in questions if str(question.get("question_id") or "") in sql_question_ids]
    predictions = run_predictions(sql_questions)
    report = evaluate_text2sql(sql_questions, gold_sql, predictions)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
