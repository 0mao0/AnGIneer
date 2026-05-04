"""评测套件编排 + 异步任务管理。"""
import threading
import time
from typing import Any, Dict, List, Optional

from evals_core.runner import base as evaluator_base
from evals_core.runner.retrieval_eval import RetrievalEvaluator
from evals_core.runner.answer_eval import AnswerEvaluator
from evals_core.runner.text2sql_eval import Text2SqlEvaluator
from evals_core.runner.sop_eval import SopEvaluator
from evals_core.storage import result_store


def _build_evaluators() -> Dict[str, Any]:
    """构建评测器映射。"""
    evaluators = {}
    for name in evaluator_base.list_evaluator_names():
        ev = evaluator_base.get_evaluator(name)
        if ev:
            evaluators[name] = ev
    return evaluators


def _average_scores(*values: Any) -> float:
    """计算多个分项分数的简单平均值。"""
    numeric_values = [float(v) for v in values if isinstance(v, (int, float))]
    if not numeric_values:
        return 0.0
    return round(sum(numeric_values) / len(numeric_values), 4)


def _determine_evaluator_name(question: Dict[str, Any]) -> str:
    """根据题目类型确定使用的评测器。"""
    task_type = str(question.get("task_type") or "").strip()
    if task_type == "analytic_sql":
        return "text2sql"
    retrieval_gold = question.get("retrieval_gold")
    answer_gold = question.get("answer_gold")
    if answer_gold:
        return "answer"
    if retrieval_gold:
        return "retrieval"
    return "answer"


def _run_single_question(
    question: Dict[str, Any],
    evaluator_name: str,
    evaluators: Dict[str, Any],
) -> Dict[str, Any]:
    """执行单题评测。"""
    evaluator = evaluators.get(evaluator_name)
    if not evaluator:
        return {"status": "error", "error": f"评测器 {evaluator_name} 未注册", "scores": {}}
    gold_data = {}
    if evaluator_name == "retrieval":
        gold_data = question.get("retrieval_gold") or {}
    elif evaluator_name == "answer":
        gold_data = question.get("answer_gold") or {}
    elif evaluator_name == "text2sql":
        gold_data = question.get("sql_gold") or {}
    elif evaluator_name == "sop":
        gold_data = question.get("sop_gold") or {}
    start_time = time.time()
    try:
        prediction = evaluator.run_prediction(question)
        scores = evaluator.evaluate(question, gold_data, prediction)
        latency_ms = int((time.time() - start_time) * 1000)
        status = "passed" if scores.get("score", 0) >= 0.5 else "failed"
        return {
            "status": status,
            "prediction": prediction,
            "scores": scores,
            "latency_ms": latency_ms,
        }
    except Exception as exc:
        latency_ms = int((time.time() - start_time) * 1000)
        return {"status": "error", "error": str(exc), "scores": {}, "latency_ms": latency_ms}


def _compute_summary(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据逐题结果计算汇总指标。"""
    if not details:
        return {"overall_score": 0.0}
    total = len(details)
    passed = sum(1 for d in details if d.get("status") == "passed")
    overall_score = round(passed / total, 4) if total else 0.0
    retrieval_scores = [d.get("scores", {}).get("hit@5", None) for d in details
                        if d.get("scores", {}).get("evaluated") and d.get("scores", {}).get("hit@5") is not None]
    answer_scores = [d.get("scores", {}).get("score", None) for d in details
                     if d.get("scores", {}).get("evaluated") and d.get("scores", {}).get("correctness_checked")]
    sql_scores = [d.get("scores", {}).get("score", None) for d in details
                  if d.get("scores", {}).get("evaluated") and d.get("scores", {}).get("execution_success") is not None]
    retrieval_avg = round(sum(retrieval_scores) / len(retrieval_scores), 4) if retrieval_scores else None
    answer_avg = round(sum(answer_scores) / len(answer_scores), 4) if answer_scores else None
    sql_avg = round(sum(sql_scores) / len(sql_scores), 4) if sql_scores else None
    by_level: Dict[str, Dict[str, int]] = {}
    for d in details:
        level = d.get("intent_level", "L1")
        if level not in by_level:
            by_level[level] = {"total": 0, "passed": 0}
        by_level[level]["total"] += 1
        if d.get("status") == "passed":
            by_level[level]["passed"] += 1
    return {
        "overall_score": overall_score,
        "total": total,
        "passed": passed,
        "retrieval_score": retrieval_avg,
        "answer_score": answer_avg,
        "sql_score": sql_avg,
        "by_level": by_level,
    }


def _run_suite_thread(run_id: str, dataset_id: str, questions: List[Dict[str, Any]]) -> None:
    """在线程中执行评测套件。"""
    evaluators = _build_evaluators()
    total = len(questions)
    for idx, question in enumerate(questions):
        question_id = str(question.get("question_id") or "")
        evaluator_name = _determine_evaluator_name(question)
        result_store.insert_run_detail({
            "run_id": run_id,
            "question_id": question_id,
            "status": "running",
        })
        result = _run_single_question(question, evaluator_name, evaluators)
        result_store.update_run_detail(run_id, question_id, {
            "status": result.get("status", "error"),
            "prediction": result.get("prediction"),
            "scores": result.get("scores"),
            "error": result.get("error"),
            "latency_ms": result.get("latency_ms"),
        })
        completed = idx + 1
        result_store.update_run_progress(run_id, completed)
    details = result_store.list_run_details(run_id)
    enriched_details = []
    for d in details:
        q = next((q for q in questions if str(q.get("question_id") or "") == d["question_id"]), {})
        enriched = {**d, "intent_level": q.get("intent_level", "L1"), "question": q.get("question", "")}
        enriched_details.append(enriched)
    summary = _compute_summary(enriched_details)
    result_store.complete_run(run_id, summary)


def start_eval_run(dataset_id: str) -> Dict[str, Any]:
    """启动评测运行（异步）。"""
    questions = result_store.list_questions(dataset_id)
    if not questions:
        raise ValueError(f"测试集 {dataset_id} 没有题目")
    run_data = result_store.create_run(dataset_id, len(questions))
    run_id = run_data["run_id"]
    thread = threading.Thread(target=_run_suite_thread, args=(run_id, dataset_id, questions), daemon=True)
    thread.start()
    return run_data


def get_eval_run(run_id: str) -> Optional[Dict[str, Any]]:
    """查询运行进度/结果。"""
    run = result_store.get_run(run_id)
    if not run:
        return None
    details = result_store.list_run_details(run_id)
    return {**run, "details": details}


def list_eval_runs(dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出历史运行记录。"""
    return result_store.list_runs(dataset_id)


def compare_runs(run_id_a: str, run_id_b: str) -> Optional[Dict[str, Any]]:
    """对比两次运行结果。"""
    run_a = get_eval_run(run_id_a)
    run_b = get_eval_run(run_id_b)
    if not run_a or not run_b:
        return None
    summary_a = run_a.get("summary_scores") or {}
    summary_b = run_b.get("summary_scores") or {}
    score_diff = {}
    for key in set(list(summary_a.keys()) + list(summary_b.keys())):
        val_a = summary_a.get(key, 0) if isinstance(summary_a.get(key), (int, float)) else 0
        val_b = summary_b.get(key, 0) if isinstance(summary_b.get(key), (int, float)) else 0
        score_diff[key] = round(val_b - val_a, 4)
    details_a = {d["question_id"]: d for d in run_a.get("details", [])}
    details_b = {d["question_id"]: d for d in run_b.get("details", [])}
    question_changes = []
    all_ids = set(list(details_a.keys()) + list(details_b.keys()))
    for qid in sorted(all_ids):
        da = details_a.get(qid, {})
        db = details_b.get(qid, {})
        status_a = da.get("status", "missing")
        status_b = db.get("status", "missing")
        if status_a != status_b:
            question_changes.append({
                "question_id": qid,
                "status_a": status_a,
                "status_b": status_b,
                "change": "improved" if status_b == "passed" and status_a != "passed" else "regressed",
            })
    return {
        "run_a": {"run_id": run_id_a, "status": run_a["status"], "summary_scores": summary_a},
        "run_b": {"run_id": run_id_b, "status": run_b["status"], "summary_scores": summary_b},
        "score_diff": score_diff,
        "question_changes": question_changes,
    }
