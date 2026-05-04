"""评测报告聚合模块。"""
import json
from typing import Any, Dict, Optional

from docs_core.evals.dataset_loader import load_eval_answer_rows, load_eval_questions, load_eval_retrieval_rows, load_eval_sql_rows
from docs_core.evals.eval_answer import evaluate_answers, run_predictions as run_answer_predictions
from docs_core.evals.eval_retrieval import evaluate_retrieval, run_predictions as run_unified_predictions
from docs_core.evals.eval_text2sql import evaluate_text2sql, run_predictions as run_sql_predictions


# 计算多个分项分数的简单平均值。
def average_scores(*values: Any) -> float:
    numeric_values = [float(value) for value in values if isinstance(value, (int, float))]
    if not numeric_values:
        return 0.0
    return round(sum(numeric_values) / len(numeric_values), 4)


# 聚合 retrieval、answer、text2sql 三类评测结果。
def build_eval_suite_report(
    dataset_id: str | None = None,
    cached_predictions: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    questions = load_eval_questions(dataset_id=dataset_id)
    gold_retrieval_rows = load_eval_retrieval_rows(dataset_id=dataset_id)
    gold_answer_rows = load_eval_answer_rows(dataset_id=dataset_id)
    gold_sql_rows = load_eval_sql_rows(dataset_id=dataset_id)
    gold_retrieval = {str(row.get("question_id") or ""): row for row in gold_retrieval_rows}
    gold_answers = {str(row.get("question_id") or ""): row for row in gold_answer_rows}
    gold_sql = {str(row.get("question_id") or ""): row for row in gold_sql_rows if row.get("question_id")}
    if cached_predictions is not None:
        unified_predictions = cached_predictions
    else:
        unified_predictions = run_unified_predictions(questions)
    sql_question_ids = set(gold_sql.keys())
    sql_questions = [question for question in questions if str(question.get("question_id") or "") in sql_question_ids]
    sql_predictions = run_sql_predictions(sql_questions)
    retrieval_report = evaluate_retrieval(questions, gold_retrieval, unified_predictions)
    answer_report = evaluate_answers(questions, gold_answers, unified_predictions)
    text2sql_report = evaluate_text2sql(sql_questions, gold_sql, sql_predictions)
    answer_health_score = average_scores(
        answer_report.get("answer_non_empty_rate"),
        answer_report.get("citation_hit_rate"),
        answer_report.get("refusal_correct_rate"),
    )
    answer_correctness_score = (
        answer_report.get("answer_correctness_rate")
        if answer_report.get("correctness_checked_total")
        else None
    )
    overall_score = average_scores(
        retrieval_report.get("recall@5"),
        answer_health_score,
        answer_correctness_score,
    )
    return {
        "summary": {
            "retrieval_score": retrieval_report.get("recall@5", 0.0),
            "answer_health_score": answer_health_score,
            "answer_correctness_score": answer_correctness_score,
            "checked_answer_total": answer_report.get("correctness_checked_total", 0),
            "overall_score": overall_score,
            "text2sql_success_score": text2sql_report.get("sql_success_rate", 0.0),
        },
        "retrieval": retrieval_report,
        "answer": answer_report,
        "text2sql": text2sql_report,
    }


# 脚本入口：输出统一评测报告。
def main() -> None:
    print(json.dumps(build_eval_suite_report(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
