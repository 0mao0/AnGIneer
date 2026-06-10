"""评测套件编排 + 异步任务管理。"""
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner import base as evaluator_base
from evals_core.runner.retrieval_eval import RetrievalEvaluator
from evals_core.runner.answer_eval import AnswerEvaluator
from evals_core.runner.text2sql_eval import Text2SqlEvaluator
from evals_core.runner.sop_eval import SopEvaluator
from angineer_core.base_utils import is_fatal_exception
from evals_core.storage import result_store

PASSED_THRESHOLD = 0.8

# 全局并发控制锁：确保同一时间只有一个评测任务在运行
_eval_lock = threading.RLock()
_current_run_id: Optional[str] = None
_stop_event: Optional[threading.Event] = None


def _generate_run_name() -> str:
    """生成运行名称，格式: {模型名}_{MMDD-HHmm}。"""
    model_name = os.getenv("ANGINEER_DEFAULT_MODEL", "eval")
    now = datetime.now()
    timestamp = now.strftime("%m%d-%H%M")
    return f"{model_name}_{timestamp}"


def stop_eval_run(run_id: str) -> bool:
    """请求停止指定运行ID的评测任务（优雅停止：完成当前题目后退出）"""
    global _stop_event
    if _current_run_id != run_id or _stop_event is None:
        return False
    _stop_event.set()
    return True


def _build_evaluators() -> Dict[str, Any]:
    """构建评测器映射。"""
    evaluators = {}
    for name in evaluator_base.list_evaluator_names():
        ev = evaluator_base.get_evaluator(name)
        if ev:
            evaluators[name] = ev
    return evaluators


def _determine_evaluator_names(question: Dict[str, Any]) -> List[str]:
    """根据题目类型确定使用的评测器列表（可同时跑多个）。"""
    task_type = str(question.get("task_type") or "").strip()
    retrieval_gold = question.get("retrieval_gold")
    answer_gold = question.get("answer_gold")
    sop_gold = question.get("sop_gold")
    sql_gold = question.get("sql_gold")
    intent_level = str(question.get("intent_level") or "")
    names = []
    if retrieval_gold:
        names.append("retrieval")
    if task_type == "analytic_sql" and sql_gold:
        names.append("text2sql")
    if answer_gold:
        names.append("answer")
    if task_type == "analytic_sql" and not answer_gold and not sql_gold:
        names.append("text2sql")
    if sop_gold or intent_level == "L3":
        names.append("sop")
    if not names:
        names.append("answer")
    return names


def _run_single_question(
    question: Dict[str, Any],
    evaluator_names: List[str],
    evaluators: Dict[str, Any],
    stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """执行单题评测，支持多评测器和阶段回调。"""
    all_scores: Dict[str, Any] = {}
    all_predictions: Dict[str, Any] = {}
    last_prediction: Dict[str, Any] = {}
    if "answer" in evaluator_names:
        primary_evaluator_name = "answer"
    elif evaluator_names:
        primary_evaluator_name = evaluator_names[0]
    else:
        primary_evaluator_name = "answer"
    primary_evaluator = evaluators.get(primary_evaluator_name)
    if not primary_evaluator:
        return {"status": "error", "error": f"评测器 {primary_evaluator_name} 未注册", "scores": {}}
    start_time = time.time()
    try:
        last_prediction = primary_evaluator.run_prediction(question, stage_callback=stage_callback)
        if "error" in last_prediction:
            latency_ms = int((time.time() - start_time) * 1000)
            return {"status": "error", "error": last_prediction["error"], "scores": {}, "latency_ms": latency_ms}
    except Exception as exc:
        latency_ms = int((time.time() - start_time) * 1000)
        return {"status": "error", "error": str(exc), "scores": {}, "latency_ms": latency_ms}
    for ev_name in evaluator_names:
        evaluator = evaluators.get(ev_name)
        if not evaluator:
            continue
        gold_data = {}
        if ev_name == "retrieval":
            gold_data = question.get("retrieval_gold") or {}
        elif ev_name == "answer":
            gold_data = question.get("answer_gold") or {}
        elif ev_name == "text2sql":
            gold_data = question.get("sql_gold") or {}
        elif ev_name == "sop":
            gold_data = question.get("sop_gold") or {}
        prediction = last_prediction
        scores = evaluator.evaluate(question, gold_data, prediction)
        all_scores[ev_name] = scores
        all_predictions[ev_name] = prediction
    primary_scores = all_scores.get(primary_evaluator_name, {})
    primary_score = primary_scores.get("score")
    if primary_score is None:
        # 尝试从其他评测器获取有效 score 作为 fallback
        fallback_score = None
        for ev_name in evaluator_names:
            if ev_name == primary_evaluator_name:
                continue
            ev_scores = all_scores.get(ev_name, {})
            candidate = ev_scores.get("score")
            if candidate is not None:
                fallback_score = candidate
                break
        if fallback_score is None:
            status = "completed"
            quality = None
        elif fallback_score < PASSED_THRESHOLD:
            status = "completed"
            quality = "wrong"
        else:
            status = "completed"
            quality = "correct"
    elif primary_score < PASSED_THRESHOLD:
        status = "completed"
        quality = "wrong"
    else:
        answer_scores = all_scores.get("answer", {})
        answer_correctness = answer_scores.get("correctness_score") if answer_scores.get("correctness_checked") else None
        if answer_correctness is not None and answer_correctness < PASSED_THRESHOLD:
            status = "completed"
            quality = "wrong"
        else:
            status = "completed"
            quality = "correct"
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "status": status,
        "quality": quality,
        "prediction": last_prediction,
        "all_predictions": all_predictions,
        "scores": primary_scores,
        "all_scores": all_scores,
        "latency_ms": latency_ms,
    }


def _compute_summary(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据逐题结果计算汇总指标。"""
    if not details:
        return {"overall_score": 0.0}
    total = len(details)
    correct = sum(1 for d in details if d.get("quality") == "correct")
    wrong = sum(1 for d in details if d.get("quality") == "wrong")
    skipped = sum(1 for d in details if d.get("status") == "completed" and d.get("quality") is None)
    errored = sum(1 for d in details if d.get("status") == "error")
    overall_score = round(correct / total, 4) if total else 0.0
    retrieval_scores = []
    answer_scores = []
    sql_scores = []
    for d in details:
        all_s = d.get("all_scores", {})
        for ev_name, s in all_s.items():
            if not s.get("evaluated"):
                continue
            if ev_name == "retrieval" and s.get("hit@5") is not None:
                retrieval_scores.append(s["hit@5"])
            elif ev_name == "answer" and s.get("correctness_checked"):
                answer_scores.append(s.get("correctness_score", s.get("score", 0)))
            elif ev_name == "text2sql" and s.get("execution_success") is not None:
                sql_scores.append(s.get("score", 0))
    retrieval_avg = round(sum(retrieval_scores) / len(retrieval_scores), 4) if retrieval_scores else None
    answer_avg = round(sum(answer_scores) / len(answer_scores), 4) if answer_scores else None
    sql_avg = round(sum(sql_scores) / len(sql_scores), 4) if sql_scores else None
    by_level: Dict[str, Dict[str, int]] = {}
    for d in details:
        level = d.get("intent_level", "L1")
        if level not in by_level:
            by_level[level] = {"total": 0, "correct": 0}
        by_level[level]["total"] += 1
        if d.get("quality") == "correct":
            by_level[level]["correct"] += 1
    return {
        "overall_score": overall_score,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "skipped": skipped,
        "errored": errored,
        "retrieval_score": retrieval_avg,
        "answer_score": answer_avg,
        "sql_score": sql_avg,
        "by_level": by_level,
    }


def _run_suite_thread(
    run_id: str, dataset_id: str, questions: List[Dict[str, Any]],
    override_doc_ids: Optional[List[str]] = None,
) -> None:
    """在线程中执行评测套件，含异常保护、并发控制和优雅停止支持。"""
    global _current_run_id, _stop_event
    
    # 获取并发控制锁（阻塞等待，直到其他评测任务完成）
    acquired = _eval_lock.acquire(timeout=0.1)
    if not acquired:
        result_store.fail_run(run_id, "已有其他评测任务正在运行，请稍后再试")
        return
    
    _current_run_id = run_id
    _stop_event = threading.Event()
    
    try:
        evaluators = _build_evaluators()
        total = len(questions)
        for idx, question in enumerate(questions):
            # 检查是否收到停止信号（在每道题目开始前检查）
            if _stop_event.is_set():
                # 优雅退出：计算已完成的汇总指标并标记为已取消
                details = result_store.list_run_details(run_id)
                enriched_details = []
                for d in details:
                    q = next((q for q in questions if str(q.get("question_id") or "") == d["question_id"]), {})
                    enriched = {**d, "intent_level": q.get("intent_level", "L1"), "question": q.get("question", "")}
                    enriched_details.append(enriched)
                summary = _compute_summary(enriched_details)
                result_store.cancel_run(run_id, summary)
                return
            
            question_id = str(question.get("question_id") or "")
            evaluator_names = _determine_evaluator_names(question)
            if override_doc_ids is not None:
                question = {**question, "doc_ids": override_doc_ids}
            result_store.insert_run_detail({
                "run_id": run_id,
                "question_id": question_id,
                "status": "running",
            })

            def _stage_callback(partial_prediction: Dict[str, Any]) -> None:
                """阶段回调：将中间结果增量写入数据库。"""
                result_store.update_run_detail(run_id, question_id, {
                    "prediction": partial_prediction,
                })

            result = _run_single_question(question, evaluator_names, evaluators, stage_callback=_stage_callback)
            result_store.update_run_detail(run_id, question_id, {
                "status": result.get("status", "error"),
                "quality": result.get("quality"),
                "prediction": result.get("prediction"),
                "scores": result.get("scores"),
                "all_scores": result.get("all_scores"),
                "all_predictions": result.get("all_predictions"),
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
    except Exception as exc:
        if is_fatal_exception(exc):
            raise
        import traceback
        traceback.print_exc()
        result_store.fail_run(run_id, str(exc))
    finally:
        # 确保清理状态并释放锁
        _current_run_id = None
        _stop_event = None
        _eval_lock.release()
        result_store.cleanup_old_runs(dataset_id, keep=3)
        result_store.cleanup_individual_runs(dataset_id)


def start_eval_run(
    dataset_id: str, question_id: Optional[str] = None, save: bool = True,
    override_doc_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """启动评测运行（异步线程），立即返回 run_id，前端轮询获取进度。"""
    if _current_run_id is not None:
        raise ValueError(f"已有评测任务正在运行 (run_id: {_current_run_id})，请等待完成后再试")
    
    all_questions = result_store.list_questions(dataset_id)
    if not all_questions:
        raise ValueError(f"测试集 {dataset_id} 没有题目")
    if question_id:
        questions = [q for q in all_questions if str(q.get("question_id") or "") == question_id]
        if not questions:
            raise ValueError(f"题目 {question_id} 不存在于测试集 {dataset_id}")
    else:
        questions = all_questions

    is_full_run = question_id is None
    run_name = _generate_run_name() if is_full_run else ""
    run_data = result_store.create_run(dataset_id, len(questions), run_name=run_name, is_full_run=is_full_run)
    run_id = run_data["run_id"]
    thread = threading.Thread(
        target=_run_suite_thread,
        args=(run_id, dataset_id, questions, override_doc_ids),
        daemon=True,
    )
    thread.start()
    return run_data


def get_eval_run(run_id: str) -> Optional[Dict[str, Any]]:
    """查询运行进度/结果，运行中时实时计算汇总指标。"""
    run = result_store.get_run(run_id)
    if not run:
        return None
    details = result_store.list_run_details(run_id)
    result = {**run, "details": details}
    if run.get("status") == "running" and not run.get("summary_scores"):
        completed_details = [d for d in details if d.get("status") not in ("pending", "running")]
        if completed_details:
            questions = result_store.list_questions(run["dataset_id"])
            enriched = []
            for d in completed_details:
                q = next((q for q in questions if str(q.get("question_id") or "") == d["question_id"]), {})
                enriched.append({**d, "intent_level": q.get("intent_level", "L1"), "question": q.get("question", "")})
            result["summary_scores"] = _compute_summary(enriched)
    return result


def list_eval_runs(dataset_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """列出历史运行记录。"""
    return result_store.list_runs(dataset_id)


def delete_eval_run(run_id: str) -> bool:
    """删除指定评测运行。"""
    return result_store.delete_run(run_id)


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
    import logging
    logger = logging.getLogger(__name__)
    logger.info(
        f"对比运行: A={run_id_a} (details={len(details_a)}, total={run_a.get('total_questions')}), "
        f"B={run_id_b} (details={len(details_b)}, total={run_b.get('total_questions')})"
    )
    question_changes = []
    all_ids = set(list(details_a.keys()) + list(details_b.keys()))
    for qid in sorted(all_ids):
        da = details_a.get(qid, {})
        db = details_b.get(qid, {})
        quality_a = da.get("quality") or da.get("status", "missing")
        quality_b = db.get("quality") or db.get("status", "missing")
        is_consistent = (quality_a == quality_b)
        change_type = None
        if not is_consistent:
            change_type = "improved" if quality_b == "correct" and quality_a != "correct" else "regressed"
        question_changes.append({
            "question_id": qid,
            "status_a": quality_a,
            "status_b": quality_b,
            "consistent": is_consistent,
            "change": change_type,
        })
    result = {
        "run_a": {
            "run_id": run_id_a,
            "status": run_a["status"],
            "summary_scores": summary_a,
            "total_questions": run_a.get("total_questions"),
            "completed_questions": run_a.get("completed_questions"),
            "details_count": len(details_a),
        },
        "run_b": {
            "run_id": run_id_b,
            "status": run_b["status"],
            "summary_scores": summary_b,
            "total_questions": run_b.get("total_questions"),
            "completed_questions": run_b.get("completed_questions"),
            "details_count": len(details_b),
        },
        "score_diff": score_diff,
        "question_changes": question_changes,
    }
    logger.info(f"对比结果: 共 {len(question_changes)} 条题目变化")
    return result
