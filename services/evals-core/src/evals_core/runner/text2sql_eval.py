"""Text-to-SQL 评测器，通过 query_engine 直接调用 SQL 链路。"""
from typing import Any, Callable, Dict, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator
from evals_core.runner._prediction_trace import enrich_prediction_trace
from evals_core.runner._query_helper import run_eval_query


class Text2SqlEvaluator(BaseEvaluator):
    """SQL 评测器，通过 query_engine 直接调用 SQL 链路。"""

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """通过 query_engine 直接调用 SQL 链路。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}

        data = run_eval_query(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            doc_ids=list(question.get("doc_ids") or []),
            session_id=f"eval-sql-{question_id}",
        )

        if "error" in data:
            return data

        sql_data = data.get("sql")
        prediction = {
            "sql": sql_data,
            "answer": data.get("answer", ""),
            "execution_status": (sql_data or {}).get("execution_status", "") if sql_data else "",
            "generated_sql": (sql_data or {}).get("generated_sql", "") if sql_data else "",
            "intent": data.get("intent", {}),
        }
        return enrich_prediction_trace(question, data, prediction)

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算 SQL 评测指标。"""
        execution_status = str(prediction.get("execution_status") or "")
        generated_sql = str(prediction.get("generated_sql") or "").strip()
        expected_sql = str(gold.get("expected_sql") or "").strip()
        success = execution_status == "success"
        match = bool(expected_sql and generated_sql == expected_sql)
        score = 1.0 if success else 0.0
        return {
            "score": score,
            "evaluated": True,
            "execution_success": success,
            "sql_exact_match": match if expected_sql else None,
            "execution_status": execution_status,
        }


register_evaluator("text2sql", Text2SqlEvaluator)
