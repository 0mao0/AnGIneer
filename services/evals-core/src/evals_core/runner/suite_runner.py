"""评测套件编排 + 异步任务管理。"""
import logging
import os
import threading
import time
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner import base as evaluator_base
from evals_core.runner import anomaly
from evals_core.runner.retrieval_eval import RetrievalEvaluator
from evals_core.runner.answer_eval import AnswerEvaluator
from evals_core.runner.sop_eval import SopEvaluator
# 注册副作用导入：probe 评测器（题目带 probe 断言块时 exclusive 接管，见 _determine_evaluator_names）
from evals_core.runner import probe_eval  # noqa: F401
# 注册副作用导入：intent 评测器（题目带 intent 路由金标块时 exclusive 接管）
from evals_core.runner import intent_eval  # noqa: F401
# 注册副作用导入：rubric 评测器（题目带 rubric 金标块时接管，RAG 生成 + 判官逐条判）
from evals_core.runner import rubric_eval  # noqa: F401
# 注册副作用导入：numeric 评测器（题目带 numeric 金标块时接管，RAG 生成 + 官方确定性数值判分，无判官）
from evals_core.runner import numeric_eval  # noqa: F401
from angineer_core.base_utils import is_fatal_exception
from evals_core.storage import result_store, retention

logger = logging.getLogger(__name__)

PASSED_THRESHOLD = 0.8


def _decide_quality(primary_evaluator_name: str, all_scores: Dict[str, Any]) -> tuple:
    """主评测器没给出分数 → quality=None（未评估），绝不拿其他评测器的分顶替。

    检索分衡量的是「找没找到」，不是「答没答对」。旧逻辑在 primary score is None 时
    会从其他评测器取分兜底，而 retrieval.score 几乎恒为 1.0 —— 判分崩掉的晚上整批题
    被它记成答对（2026-09-23：476 题崩、442 题记 correct，当晚 88.78% vs 同日真判
    83.46%；2026-09-25：915 题崩、卡片报 92.4% vs 补判后 87.31%，虚高 53 题）。
    近六个 run 实测：走进这条分支的只有判分崩（semantic_fallback）的题，正常晚上 0 题，
    故删掉跨评测器兜底对健康链路零影响。未评估题的下场：
    - _compute_summary 计入 skipped，overall=correct/total 分母不变（自动按 0 分计）；
    - 门禁 gate.passed/failed 只认 correct/wrong → 过渡矩阵落 skip，不参与回归判定。
    """
    primary_score = (all_scores.get(primary_evaluator_name) or {}).get("score")
    if primary_score is None:
        return "completed", None
    if primary_score < PASSED_THRESHOLD:
        return "completed", "wrong"
    answer_scores = all_scores.get("answer") or {}
    semantic_passed = answer_scores.get("semantic_passed")
    if semantic_passed is not None:
        # 单阈值权威：判官已按题集 semantic_threshold（默认 0.65）出过通过与否的裁决，
        # 终审不得再拿 0.8 对同一个 correctness_score 二次过闸——否则 0.65~0.8 区间的
        # 「判官说通过」全被终审翻成 wrong（2026-09-30 复核 run-f18ce01a6587：15 题
        # semantic_passed=True 且零 failed_checks 仍判 wrong，逐题复核 90% 为冤案）。
        return ("completed", "correct") if semantic_passed else ("completed", "wrong")
    answer_correctness = answer_scores.get("correctness_score") if answer_scores.get("correctness_checked") else None
    if answer_correctness is not None and answer_correctness < PASSED_THRESHOLD:
        return "completed", "wrong"
    return "completed", "correct"

# 在跑 run 的停止信号登记表：run_id -> Event。
# 旧实现是 _current_run_id/_stop_event 两个模块级单例，结构上只容得下一个在跑任务：
# 「停止」按 run_id 比对单例，第二个 run 一起来就会串台。并发由用户在前端弹框确认
# （「已有评测在跑」→ 取消/确定），状态必须按 run 分开存（2026-09-27）。
_stop_events: Dict[str, threading.Event] = {}
_stop_events_lock = threading.Lock()


def is_running_here(run_id: str) -> bool:
    """该 run 是否由本进程正在执行（与 DB 的 running 状态不同：僵尸行不算）。"""
    return run_id in _stop_events


def release_native_memory() -> None:
    """评测跑完后把已释放内存归还操作系统：glibc 各 arena 的 freelist 不会自动 madvise，
    千题级检索上下文（峰值 RSS 2G+）留在堆里表现为服务常驻虚高（2026-09-24 生产实测：
    nightly 结束后 RSS 仍挂 2.3G、swap 多吃 1.7G，3.6G 宿主机仅剩 300M available）。
    malloc_trim(0) 跨所有 arena 归还整页空闲块；失败静默（Windows 无此符号）。"""
    import gc

    gc.collect()
    try:
        import ctypes

        ctypes.CDLL("libc.so.6", use_errno=True).malloc_trim(0)
    except Exception:  # noqa: BLE001
        pass


def caliber_fingerprint() -> Dict[str, Any]:
    """判分口径指纹：评测引擎 / 扩展维度开关 / judge 模型 / steps 固化清单任一变化即变。

    nightly 自动断点续跑（pipeline._find_resume_candidate）据此拒绝跨口径缝合已完成题——
    续跑复用的是旧 run 的判分结果，口径变了这些结果就不可比。"""
    import hashlib as _hl

    scale_fix = ""
    try:
        from evals_core.runner.judge_deepeval import _GEVAL_CRITERIA as _criteria
        from evals_core.runner.judge_deepeval import _GEVAL_STEPS as _steps
        from evals_core.runner.judge_deepeval import _JUDGE_SCALE_FIX_VERSION as _scale_fix
        from angineer_core.prompts.answer_eval import SEMANTIC_EVAL_PROMPT as _legacy_prompt

        steps_fp = _hl.sha256(
            (_criteria + "\n".join(_steps) + _legacy_prompt).encode("utf-8")
        ).hexdigest()[:12]
        scale_fix = _scale_fix
    except Exception:  # noqa: BLE001 无 deepeval 环境 steps_fp 留空（legacy 口径本就不依赖它）
        steps_fp = ""
    return {
        "eval_engine": (os.getenv("EVAL_ENGINE", "legacy") or "legacy").strip().lower(),
        "deepval_extra": (os.getenv("EVAL_DEEPVAL_EXTRA", "1") or "1").strip().lower(),
        "judge_model": (os.getenv("EVAL_JUDGE_MODEL") or "").strip(),
        "steps_fp": steps_fp,
        # 双刻度归一化版本：改动此逻辑必须换版本号，防断点续跑把修前/修后结果缝合比对
        "judge_scale_fix": scale_fix,
    }


def _manifest_with_judge(
    config_name: Optional[str],
    judge_config_name: Optional[str],
    answer_format: Optional[str] = None,
) -> Dict[str, Any]:
    """run manifest + 判分模型记录（UI 弹框选定的评价模型，供历史 item 回溯与展示）。"""
    from angineer_core.run_manifest import build_run_manifest

    manifest = build_run_manifest(config_name)
    judge = str(judge_config_name or "").strip()
    if judge:
        manifest["judge_config"] = judge
    # 口径指纹入 config_snapshot：nightly 断点续跑的唯一性守卫（见 caliber_fingerprint）
    manifest["caliber_fp"] = caliber_fingerprint()
    # §7.7 注入实验留痕（预注册判据：缺留痕判实验无效）——注入文本原文 + 开关态
    injected = str(answer_format or "").strip()
    manifest["answer_format"] = {"enabled": bool(injected), "text": injected or None}
    return manifest


def _generate_run_name(config_name: Optional[str] = None) -> str:
    """生成运行名称，格式: {模型名}_{MMDD-HHmm}。"""
    model_name = config_name or os.getenv("ANGINEER_DEFAULT_MODEL", "eval")
    now = datetime.now()
    timestamp = now.strftime("%m%d-%H%M")
    return f"{model_name}_{timestamp}"


def stop_eval_run(run_id: str) -> bool:
    """请求停止指定运行ID的评测任务（优雅停止：完成当前题目后退出）。

    并发下每个 run 有各自的停止信号，按 run_id 取；取不到才走僵尸清理分支。
    """
    stop_event = _stop_events.get(run_id)
    if stop_event is None:
        # 当前进程没有该运行的任务：若 DB 中仍是 running（僵尸状态，后端重启后线程已死），
        # 直接按已中断收尾，避免前端"停止"永远 404。
        run = result_store.get_run(run_id)
        if run and run.get("status") == "running":
            details = result_store.list_run_details(run_id)
            questions = result_store.list_questions(run.get("dataset_id") or "")
            qmap = {str(q.get("question_id") or ""): q for q in questions}
            enriched = [_enrich_detail_with_question(d, qmap.get(str(d.get("question_id") or ""), {})) for d in details]
            summary = _compute_summary(enriched)
            # 与启动清扫同语义：线程已死（进程被杀后用户点了"停止"清理僵尸），允许 nightly 续跑复活
            summary["interrupted_by_startup_sweep"] = True
            result_store.cancel_run(run_id, summary)
            return True
        return False
    stop_event.set()
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
    # 意图路由题 exclusive：只跑分类器路由断言，不进检索/问答/判官链路（intent-router 类题集）
    if question.get("intent_gold"):
        return ["intent"]
    # 探针题 exclusive：只跑检索断言，不进问答/判官链路（clause-probe 类题集）
    if question.get("probe_gold"):
        return ["probe"]
    # 数值容差题（OfficeQA 类）：跑 RAG 生成 + 官方 vendored 判分器确定性判，numeric 恒为 primary。
    # 检索金标在时并列跑 retrieval（同 rubric 纪律：retrieval 放后，防检索分顶假绿）。
    if question.get("numeric_gold"):
        return ["numeric", "retrieval"] if question.get("retrieval_gold") else ["numeric"]
    # 评分细则题（GDP.pdf 类）：跑 RAG 生成 + 判官逐条判 rubric，rubric 恒为 primary。
    # 检索金标在时并列跑 retrieval（放后面，避免 primary 被检索分顶成假绿，见 _decide_quality）。
    if question.get("rubric_gold"):
        return ["rubric", "retrieval"] if question.get("retrieval_gold") else ["rubric"]
    retrieval_gold = question.get("retrieval_gold")
    answer_gold = question.get("answer_gold")
    sop_gold = question.get("sop_gold")
    intent_level = str(question.get("intent_level") or "")
    names = []
    if retrieval_gold:
        names.append("retrieval")
    if answer_gold:
        names.append("answer")
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
    prediction_override: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """执行单题评测，支持多评测器和阶段回调。

    prediction_override 非空时跳过问答链路（run_prediction），直接复用存量 prediction
    重新判分（rescore）。用于 judge 断连导致的 semantic_fallback 题补判：
    重答会引入答案抖动、混淆「judge 故障」与「模型回退」，仅重判分才是无副作用补判。
    """
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
    if prediction_override is not None and "error" not in prediction_override:
        last_prediction = prediction_override
    else:
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
        elif ev_name == "probe":
            gold_data = question.get("probe_gold") or {}
        elif ev_name == "intent":
            gold_data = question.get("intent_gold") or {}
        elif ev_name == "answer":
            gold_data = question.get("answer_gold") or {}
        elif ev_name == "sop":
            gold_data = question.get("sop_gold") or {}
        elif ev_name == "rubric":
            gold_data = question.get("rubric_gold") or {}
        elif ev_name == "numeric":
            gold_data = question.get("numeric_gold") or {}
        prediction = last_prediction
        scores = evaluator.evaluate(question, gold_data, prediction)
        all_scores[ev_name] = scores
        all_predictions[ev_name] = prediction
    status, quality = _decide_quality(primary_evaluator_name, all_scores)
    latency_ms = int((time.time() - start_time) * 1000)
    return {
        "status": status,
        "quality": quality,
        "prediction": last_prediction,
        "all_predictions": all_predictions,
        "scores": all_scores.get(primary_evaluator_name, {}),
        "all_scores": all_scores,
        "latency_ms": latency_ms,
    }


def _compute_summary(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """根据逐题结果计算汇总指标。"""
    if not details:
        return {"overall_score": 0.0}

    # 按题目去重：同一 question_id 只保留最早一条详情，避免续跑残留重复行导致总数虚高
    seen: set = set()
    deduped: List[Dict[str, Any]] = []
    for d in details:
        qid = str(d.get("question_id") or "")
        if qid in seen:
            continue
        seen.add(qid)
        deduped.append(d)
    details = deduped

    def _append_group_score(bucket: Dict[str, List[float]], name: str, score: Any) -> None:
        """向分组桶追加分数。"""
        if score is None:
            return
        bucket.setdefault(name, []).append(float(score))

    total = len(details)
    correct = sum(1 for d in details if d.get("quality") == "correct")
    wrong = sum(1 for d in details if d.get("quality") == "wrong")
    skipped = sum(1 for d in details if d.get("status") == "completed" and d.get("quality") is None)
    errored = sum(1 for d in details if d.get("status") == "error")

    def _scores_of(d: Dict[str, Any]) -> Dict[str, Any]:
        s = d.get("scores")
        return s if isinstance(s, dict) else {}

    # 哨兵 b：run 级可见的"被吞 LLM 失败"与"吞错式拒答"计数——
    # 拒答集满分但 llm_error_questions 高企 = 假满分（2026-09-06 17:08 实踩 100 分）
    llm_error_questions = sum(1 for d in details if _scores_of(d).get("llm_error_count"))
    refusal_via_error_questions = sum(1 for d in details if _scores_of(d).get("refusal_via_error"))
    # 观测标注：final_outcome 终态分布（拒答归因用——拒答题里 model_refusal_kept vs
    # guard_replaced_* vs finalized_refusal 的占比直接说明「拒答是谁产生的」）
    final_outcome_counts: Dict[str, int] = {}
    for d in details:
        fo = _scores_of(d).get("final_outcome")
        if fo:
            final_outcome_counts[str(fo)] = final_outcome_counts.get(str(fo), 0) + 1
    overall_score = round(correct / total, 4) if total else 0.0
    retrieval_scores = []
    answer_scores = []
    sql_scores = []
    grouped_scores_raw: Dict[str, Dict[str, List[float]]] = {
        "question_type": {},
        "doc_id": {},
        "failure_bucket": {},
        "question_family": {},
        "variant_type": {},
        "runtime_flag": {},
    }
    for d in details:
        all_s = d.get("all_scores") or {}
        for ev_name, s in all_s.items():
            if not s.get("evaluated"):
                continue
            if ev_name == "retrieval" and (s.get("score") is not None or s.get("hit@5") is not None):
                # score 为有效粒度 hit@5：有 section 标注取 section 粒度，否则取 doc 粒度；
                # 兼容旧数据/fixture 中只有 hit@5 没有 score 的情况
                retrieval_value = s.get("score")
                if retrieval_value is None:
                    retrieval_value = s.get("hit@5")
                retrieval_scores.append(retrieval_value)
                _append_group_score(
                    grouped_scores_raw["question_type"],
                    str(s.get("question_type") or "unknown"),
                    retrieval_value,
                )
                _append_group_score(
                    grouped_scores_raw["doc_id"],
                    str((d.get("doc_ids") or ["unknown"])[0]),
                    retrieval_value,
                )
                _append_group_score(
                    grouped_scores_raw["failure_bucket"],
                    str(s.get("failure_bucket") or "unknown"),
                    1.0,
                )
                _append_group_score(
                    grouped_scores_raw["question_family"],
                    str(d.get("question_family") or "unknown"),
                    retrieval_value,
                )
                _append_group_score(
                    grouped_scores_raw["variant_type"],
                    str(d.get("variant_type") or "canonical"),
                    retrieval_value,
                )
                for runtime_flag in list(d.get("runtime_flags") or []):
                    _append_group_score(
                        grouped_scores_raw["runtime_flag"],
                        str(runtime_flag),
                        retrieval_value,
                    )
            elif ev_name == "answer" and s.get("correctness_checked"):
                score_value = s.get("correctness_score")
                if score_value is None:
                    score_value = s.get("score")
                if score_value is not None:
                    answer_scores.append(score_value)
    retrieval_avg = round(sum(retrieval_scores) / len(retrieval_scores), 4) if retrieval_scores else None
    answer_avg = round(sum(answer_scores) / len(answer_scores), 4) if answer_scores else None
    sql_avg = round(sum(sql_scores) / len(sql_scores), 4) if sql_scores else None
    # 拒答专项：refusal_expected=true 的拒答题正确率与不可答幻觉数
    refusal_total = 0
    refusal_correct_count = 0
    # 二段判定拆分（2026-10-09）：未拒的答案按证据支持度分「有据未拒」与「真幻觉」
    refusal_miss_grounded = 0
    refusal_miss_unsupported = 0
    for d in details:
        answer_s = (d.get("all_scores") or {}).get("answer") or {}
        if not answer_s.get("evaluated") or not answer_s.get("refusal_expected"):
            continue
        refusal_total += 1
        if answer_s.get("refusal_correct"):
            refusal_correct_count += 1
        elif answer_s.get("evidence_supported") is True:
            refusal_miss_grounded += 1
        elif answer_s.get("evidence_supported") is False:
            refusal_miss_unsupported += 1
    refusal_accuracy = round(refusal_correct_count / refusal_total, 4) if refusal_total else None
    by_level: Dict[str, Dict[str, int]] = {}
    for d in details:
        level = d.get("intent_level", "L1")
        if level not in by_level:
            by_level[level] = {"total": 0, "correct": 0}
        by_level[level]["total"] += 1
        if d.get("quality") == "correct":
            by_level[level]["correct"] += 1
    grouped_scores = {
        group_name: {
            item_name: round(sum(values) / len(values), 4) if group_name != "failure_bucket" else int(sum(values))
            for item_name, values in items.items()
        }
        for group_name, items in grouped_scores_raw.items()
    }
    return {
        "overall_score": overall_score,
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "skipped": skipped,
        "errored": errored,
        # judge 失败必须独立可见（2026-09-05 教训：fallback 静默缩分母，污染分数无提示）
        "judge_failed_count": anomaly.judge_failed_count(details),
        "anomaly_count": anomaly.judge_failed_count(details) + errored,
        # 哨兵 b：作答链路被吞 LLM 失败的题数与其中"吞错式拒答"题数（满分可信度判据）
        "llm_error_questions": llm_error_questions,
        "refusal_via_error_questions": refusal_via_error_questions,
        "final_outcome_counts": final_outcome_counts,
        "retrieval_score": retrieval_avg,
        "answer_score": answer_avg,
        "sql_score": sql_avg,
        "refusal_total": refusal_total,
        "refusal_correct": refusal_correct_count,
        "refusal_accuracy": refusal_accuracy,
        "hallucination_on_unanswerable": (refusal_total - refusal_correct_count) if refusal_total else 0,
        # 真幻觉口径：未拒且答案不被证据支持（有据未拒不计入；未判定的既不进分子也不进分母）
        "refusal_miss_grounded": refusal_miss_grounded,
        "refusal_miss_unsupported": refusal_miss_unsupported,
        "by_level": by_level,
        "grouped_scores": grouped_scores,
        # 判分引擎留痕（legacy/deepeval；混合时逗号并列）——跨 run 可比性判据
        "eval_engine": ",".join(sorted({
            str(((d.get("all_scores") or {}).get("answer") or {}).get("eval_engine") or "legacy")
            for d in details
        })),
    }


def _enrich_detail_with_question(detail: Dict[str, Any], question: Dict[str, Any]) -> Dict[str, Any]:
    """把题目元信息补回运行详情，保证第二轮维度可观测。"""
    prediction = detail.get("prediction") or {}
    return {
        **detail,
        "intent_level": question.get("intent_level", "L1"),
        "question": question.get("question", ""),
        "doc_ids": list(question.get("doc_ids") or []),
        "question_family": str(question.get("question_family") or ""),
        "variant_type": str(question.get("variant_type") or "canonical"),
        "perturbation_tags": list(question.get("perturbation_tags") or []),
        "runtime_flags": list(prediction.get("runtime_flags") or []),
    }


def _eval_concurrency() -> int:
    """评测并发度：EVAL_CONCURRENCY env（默认 3，<=1 时走串行原逻辑）。"""
    try:
        workers = int(os.getenv("EVAL_CONCURRENCY", "3").strip() or "1")
    except ValueError:
        workers = 1
    return max(1, workers)


def _run_one_worker(
    question: Dict[str, Any],
    evaluator_names: List[str],
    stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    prediction_override: Optional[Dict[str, Any]] = None,
) -> tuple:
    """并发 worker：独立 evaluator 副本跑单题，返回 (question_id, result)。"""
    evaluators = _build_evaluators()
    result = _run_single_question(
        question, evaluator_names, evaluators, stage_callback=stage_callback,
        prediction_override=prediction_override,
    )
    return str(question.get("question_id") or ""), result


def _run_questions_concurrent(
    *,
    run_id: str,
    questions: List[Dict[str, Any]],
    pre_done: Dict[str, Dict[str, Any]],
    in_place: bool,
    pre_done_count: int,
    workers: int,
    stop_event: threading.Event,
    override_doc_ids: Optional[List[str]],
    config_name: Optional[str],
    rescore_map: Optional[Dict[str, Dict[str, Any]]] = None,
    judge_config_name: Optional[str] = None,
    answer_format: Optional[str] = None,
) -> int:
    """线程池并行跑题：提交阶段检查停止信号，as_completed 收结果写库。"""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    executed = 0
    pending: Dict[Any, str] = {}
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for question in questions:
            if stop_event.is_set():
                break
            question_id = str(question.get("question_id") or "")
            if question_id in pre_done:
                if not in_place:
                    detail = pre_done[question_id]
                    result_store.insert_run_detail({
                        "run_id": run_id,
                        "question_id": question_id,
                        "status": detail.get("status", "completed"),
                        "quality": detail.get("quality"),
                        "prediction": detail.get("prediction"),
                        "scores": detail.get("scores"),
                        "all_scores": detail.get("all_scores"),
                        "all_predictions": detail.get("all_predictions"),
                        "error": detail.get("error"),
                        "latency_ms": detail.get("latency_ms"),
                    })
                result_store.update_run_progress(run_id, pre_done_count + executed)
                continue
            evaluator_names = _determine_evaluator_names(question)
            prepared = dict(question)
            # 真值判定（非 `is not None`）：空列表 = 不覆盖。曾因「空数组也当覆盖」+ UI 把
            # 「文档筛选默认全选」当作用域下发，整套题目的自带 doc 绑定被顶成全库检索
            # （2026-09-30 FinanceBench 生产 46% 假摔事故根因）。只有非空才是显式收窄。
            if override_doc_ids:
                prepared["doc_ids"] = override_doc_ids
            if config_name:
                prepared["config_name"] = config_name
            if judge_config_name:
                prepared["judge_config_name"] = judge_config_name
            if answer_format:
                prepared["answer_format"] = answer_format

            def _task(prep: Dict[str, Any], names, override, qid: str = question_id):
                # 停止命令后仍在池队列里的任务：不执行、不改状态行（保持 pending
                # 待评测）、不计进度。旧实现停止信号只在 submit 循环检查，全部题
                # 早已入池，并发模式点"停止评测"形同虚设（2026-09-06 用户实踩）。
                if stop_event.is_set():
                    return qid, {"skipped_by_stop": True}
                # running 状态必须如实反映"真正开始执行"：线程池分配到 worker 时才写。
                # 旧实现在 submit 循环就为全部排队题预写 running，池子只放行 N 个执行，
                # 页面因此"全部评测中"、实时统计失真（2026-09-06 用户实踩）。
                result_store.delete_run_detail(run_id, qid)
                result_store.insert_run_detail({
                    "run_id": run_id,
                    "question_id": qid,
                    "status": "running",
                })

                def stage_callback(partial_prediction: Dict[str, Any], _qid: str = qid) -> None:
                    result_store.update_run_detail(run_id, _qid, {"prediction": partial_prediction})

                return _run_one_worker(prep, names, stage_callback, override)

            future = pool.submit(_task, prepared, evaluator_names, (rescore_map or {}).get(question_id))
            pending[future] = question_id

        for future in as_completed(pending):
            question_id = pending[future]
            try:
                _, result = future.result()
            except Exception as exc:  # noqa: BLE001
                result = {"status": "error", "error": str(exc), "scores": {}}
            if result.get("skipped_by_stop"):
                continue  # 停止后未执行的排队题：保持 pending，不计进度
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
            executed += 1
            result_store.update_run_progress(run_id, pre_done_count + executed)
    return executed


def _finish_cancelled(run_id: str, questions: List[Dict[str, Any]]) -> None:
    """收到停止信号后的统一结算：按已完成部分计算汇总并标记 run 为已取消。
    并发/串行两路共用——旧实现并发路径停止后落回 complete_run，
    取消的评测被记成"完成"。"""
    details = result_store.list_run_details(run_id)
    enriched_details = []
    for d in details:
        q = next((q for q in questions if str(q.get("question_id") or "") == d["question_id"]), {})
        enriched_details.append(_enrich_detail_with_question(d, q))
    summary = _compute_summary(enriched_details)
    result_store.cancel_run(run_id, summary)


def _run_suite_thread(
    run_id: str, dataset_id: str, questions: List[Dict[str, Any]],
    override_doc_ids: Optional[List[str]] = None,
    pre_done: Optional[Dict[str, Dict[str, Any]]] = None,
    in_place: bool = False,
    config_name: Optional[str] = None,
    rescore_map: Optional[Dict[str, Dict[str, Any]]] = None,
    judge_config_name: Optional[str] = None,
    workers_override: Optional[int] = None,
    answer_format: Optional[str] = None,
) -> None:
    """在线程中执行评测套件，含异常保护、并发控制和优雅停止支持。

    pre_done: 断点续跑时，question_id -> 已完成详情 的映射。
    这些题目直接复用旧结果，只执行剩余题目；in_place=True 时详情已在原 run 记录中，
    不重复插入，仅计数进度。

    rescore_map: question_id -> 存量 prediction。命中的题目跳过问答链路仅重判分
    （judge 断连 fallback 题的无抖动补判，见 _run_single_question 文档）。

    并发：EVAL_CONCURRENCY（默认 3）>1 时用线程池并行跑题，每个 worker 独立构建
    evaluator 实例（共享安全）；数据库层为 WAL + thread-local 连接，天然支持并发写。
    """
    pre_done = pre_done or {}
    pre_done_count = len(pre_done)
    executed = 0

    # 并发由调用方把关（前端弹框确认 allow_concurrent），这里只登记本 run 的停止信号。
    # 旧实现用全局锁把并发掐死：拿不到锁就 fail_run("已有其他评测任务正在运行")，
    # 用户除了撞一条 toast 别无选择（2026-09-27 用户要求改成自己拍板）。
    stop_event = threading.Event()
    with _stop_events_lock:
        _stop_events[run_id] = stop_event

    try:
        total = len(questions)
        # 状态机预写：本次要执行的题先落 pending（排队中）明细行，worker 真正开始
        # 才升 running、跑完升 completed——三态如实。旧实现 submit 循环即为全部题
        # 预写 running，池子只放行 N 个执行，页面"25 题全评测中"无从分辨进度
        # （2026-09-06 用户实踩）。pre_done 题由下方既有分支按完成态复用，不预写。
        for question in questions:
            qid = str(question.get("question_id") or "")
            if qid in pre_done:
                continue
            result_store.delete_run_detail(run_id, qid)
            result_store.insert_run_detail({
                "run_id": run_id,
                "question_id": qid,
                "status": "pending",
            })
        # 每 run 并发数：请求显式指定（多道矩阵按道限流）优先，缺省沿用环境档
        workers = max(1, int(workers_override)) if workers_override else _eval_concurrency()
        if workers > 1:
            executed = _run_questions_concurrent(
                run_id=run_id,
                questions=questions,
                pre_done=pre_done,
                in_place=in_place,
                pre_done_count=pre_done_count,
                workers=workers,
                stop_event=stop_event,
                override_doc_ids=override_doc_ids,
                config_name=config_name,
                rescore_map=rescore_map,
                judge_config_name=judge_config_name,
                answer_format=answer_format,
            )
            if stop_event.is_set():
                _finish_cancelled(run_id, questions)
                return
        else:
            evaluators = _build_evaluators()
            for idx, question in enumerate(questions):
                # 检查是否收到停止信号（在每道题目开始前检查）
                if stop_event.is_set():
                    _finish_cancelled(run_id, questions)
                    return

                question_id = str(question.get("question_id") or "")
                # 断点续跑：已完成的题目直接复用旧结果
                if question_id in pre_done:
                    if not in_place:
                        detail = pre_done[question_id]
                        result_store.insert_run_detail({
                            "run_id": run_id,
                            "question_id": question_id,
                            "status": detail.get("status", "completed"),
                            "quality": detail.get("quality"),
                            "prediction": detail.get("prediction"),
                            "scores": detail.get("scores"),
                            "all_scores": detail.get("all_scores"),
                            "all_predictions": detail.get("all_predictions"),
                            "error": detail.get("error"),
                            "latency_ms": detail.get("latency_ms"),
                        })
                    result_store.update_run_progress(run_id, pre_done_count + executed)
                    continue

                evaluator_names = _determine_evaluator_names(question)
                # 同 _execute 主路径：空列表 = 不覆盖（真值判定，见上文事故注释）
                if override_doc_ids:
                    question = {**question, "doc_ids": override_doc_ids}
                if config_name:
                    question = {**question, "config_name": config_name}
                if judge_config_name:
                    question = {**question, "judge_config_name": judge_config_name}
                if answer_format:
                    question = {**question, "answer_format": answer_format}
                # 清理该题残留/重复详情行，避免续跑后同一题出现多条记录
                result_store.delete_run_detail(run_id, question_id)
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

                result = _run_single_question(
                    question, evaluator_names, evaluators, stage_callback=_stage_callback,
                    prediction_override=(rescore_map or {}).get(question_id),
                )
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
                executed += 1
                result_store.update_run_progress(run_id, pre_done_count + executed)
        details = result_store.list_run_details(run_id)
        enriched_details = []
        for d in details:
            q = next((q for q in questions if str(q.get("question_id") or "") == d["question_id"]), {})
            enriched = _enrich_detail_with_question(d, q)
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
        # 注销本 run 的停止信号（并发下别的 run 各有各的，互不影响）
        with _stop_events_lock:
            _stop_events.pop(run_id, None)
        # 三级保留策略（≤3天全量/3–90天裁过程快照/>90天删，基线与 running 保护）取代
        # 旧"仅保留最近 3 轮"——后者会在 90 天窗口内就把旧 run 删光（2026-09-15 磁盘策略）。
        # best-effort：清理失败只留日志，绝不影响本轮评测结论。
        try:
            retention_stats = retention.enforce_after_run()
            if retention_stats["compacted_runs"] or retention_stats["deleted_runs"]:
                logger.info("run 保留策略: %s", {k: v for k, v in retention_stats.items() if v})
        except Exception:  # noqa: BLE001
            logger.exception("run 保留策略执行失败（下轮再试）")
        result_store.cleanup_individual_runs(dataset_id)
        # 本轮检索上下文/判分文本的已释放内存归还 OS（服务与 nightly 同进程，不还则常驻虚高）
        try:
            release_native_memory()
        except Exception:  # noqa: BLE001
            logger.exception("归还内存失败（无害，下轮再试）")


def _pid_alive(pid: int) -> bool:
    """属主进程是否存活（无第三方依赖，Windows/Linux 双兼容）。

    注意 Windows 上 os.kill(pid, 0) 不是探活而是 TerminateProcess，绝不能用。
    PID 复用可能误判为"活"——后果只是推迟该行清扫（下次重启再收），
    远好于把别的活进程正在跑的 run 误判为死而取消。"""
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        ERROR_ACCESS_DENIED = 5
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # 拒绝访问说明进程存在（属主是别的用户会话），视为存活
            return kernel32.GetLastError() == ERROR_ACCESS_DENIED
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return True


def sweep_interrupted_runs() -> int:
    """启动清扫：服务被强杀/重启后，评测线程已消失但 DB 行仍是 running——
    历史记录永远显示"评测中"、页面加载还会对幽灵 run 恢复轮询假进度
    （2026-09-06 实踩：停止无效的 20/25 僵尸行）。按实况标记为已取消并写
    真实的部分汇总；"继续评测"按钮随即可断点续跑。返回清扫条数。

    所有权判定表（2026-10-04 容器化修复，req-nightly-interrupt-resume §2-B1）：
    仅「owner 是另一个活着的进程」才放行（09-06 多实例 53/487 保护）；owner==self 但
    本进程内存无此 run = pid 复用的幽灵（docker 主进程恒 PID 1，旧判定 os.kill(1,0)
    恒活 → 回收分支成死代码）；owner 已死 / owner_pid=0 历史行照旧回收。"""
    swept = 0
    self_pid = os.getpid()
    for r in result_store.list_runs():
        if r.get("status") != "running" or is_running_here(r.get("run_id") or ""):
            continue
        owner = int(r.get("owner_pid") or 0)
        if owner > 0 and owner != self_pid and _pid_alive(owner):
            continue
        details = result_store.list_run_details(r["run_id"], light=True)
        completed = [d for d in details if d.get("status") not in ("pending", "running")]
        correct = sum(1 for d in completed if d.get("quality") == "correct")
        wrong = sum(1 for d in completed if d.get("quality") == "wrong")
        errored = sum(1 for d in completed if d.get("status") == "error")
        total = r.get("total_questions") or len(details)
        summary = {
            "overall_score": 0.0, "total": total, "correct": correct,
            "wrong": wrong, "skipped": max(0, total - len(completed)), "errored": errored,
            # 中断盖章（2026-09-12 部署重建砸 run 实踩）：nightly 断点续跑只认带章的 cancelled，
            # 人为 stop 走 _stop_event 优雅路径不经过此处、无章 → 不会被自动复活
            "interrupted_by_startup_sweep": True,
        }
        result_store.cancel_run(r["run_id"], summary)
        swept += 1
    return swept


class EvalBusyError(RuntimeError):
    """已有评测正在跑：调用方须显式确认（allow_concurrent=True）才能并发启动。

    携带在跑清单供前端弹框展示（哪些题集、跑到第几题），由用户自己决定是否继续。
    """

    def __init__(self, running: List[Dict[str, Any]]):
        self.running = running
        labels = "；".join(
            f"{r.get('dataset_title') or r.get('dataset_id')}"
            f"（{r.get('completed_questions')}/{r.get('total_questions')}）"
            for r in running
        )
        super().__init__(f"已有 {len(running)} 个评测正在运行：{labels}")


def list_running_runs() -> List[Dict[str, Any]]:
    """当前正在跑的 run 清单（DB status=running），带题集标题供弹框展示。

    只看 DB：进程内登记表 _stop_events 只覆盖本进程，而用户看到的是页面上
    标记「评测中」的记录（含别的实例/僵尸行，僵尸由启动清扫回收）。
    """
    out: List[Dict[str, Any]] = []
    for run in result_store.list_runs():
        if run.get("status") != "running":
            continue
        dataset = result_store.get_dataset(run.get("dataset_id") or "") or {}
        snapshot = run.get("config_snapshot") or {}
        out.append({
            "run_id": run.get("run_id"),
            "dataset_id": run.get("dataset_id"),
            "dataset_title": dataset.get("title") or run.get("dataset_id"),
            "run_name": run.get("run_name") or "",
            "model": snapshot.get("model") or "",
            "completed_questions": int(run.get("completed_questions") or 0),
            "total_questions": int(run.get("total_questions") or 0),
            "started_at": run.get("started_at") or "",
        })
    return out


def start_eval_run(
    dataset_id: str, question_id: Optional[str] = None, save: bool = True,
    override_doc_ids: Optional[List[str]] = None, resume_run_id: Optional[str] = None,
    config_name: Optional[str] = None, rescore_question_ids: Optional[List[str]] = None,
    judge_config_name: Optional[str] = None, restart_run_id: Optional[str] = None,
    allow_concurrent: bool = False, workers: Optional[int] = None,
    answer_format: Optional[str] = None,
) -> Dict[str, Any]:
    """启动评测运行（异步线程），立即返回 run_id，前端轮询获取进度。

    config_name=运行（被测）模型；judge_config_name=评价模型（UI 新增评测弹框选定，
    判分候选链首位、失败回退环境链），记录进 run manifest 供历史 item 回溯与展示。

    answer_format=「答案收尾形态」注入文本（OfficeQA 注入实验 §7.7）：非空时铺到每题、
    仅 QA 档与 L3 复杂档系统提示词追加；注入原文与开关态记进 run manifest（缺留痕判实验无效）。

    allow_concurrent=False（默认）时若已有在跑的评测，抛 EvalBusyError（带在跑清单）；
    用户在弹框里选「确定」后由前端带 allow_concurrent=True 重发——并发与否是用户的
    判断（判分与问答链路打同一套后端，双跑会互相拖慢），不是系统的硬拦截。


    resume_run_id 非空时进行断点续跑：复用该 run 中已完成的题目结果，
    只执行剩余题目，最后合并为一份完整 run。

    restart_run_id 非空时原地重来（UI「重来」按钮）：清空该 run 旧明细与进度、
    复用同一条记录重跑全部题目，不再新增 item。与 resume_run_id 互斥。

    rescore_question_ids（仅配合 resume_run_id）：这些题从 pre_done 排除、不走问答链路，
    直接复用该 run 存量 prediction 重新判分——judge 断连 fallback 题的无抖动补判通道。
    存量行没有可用 prediction 的题自动降级为整题重跑。
    """
    if rescore_question_ids and not resume_run_id:
        raise ValueError("rescore_question_ids 仅在 resume_run_id 续跑时有意义")
    if restart_run_id and resume_run_id:
        raise ValueError("restart_run_id 与 resume_run_id 互斥（重来=全量重跑，续跑=复用已完成）")
    if not allow_concurrent:
        # 重来/续跑的目标 run 自己可能仍是 running（用户刚点了重来）：不算「别人在跑」
        self_ids = {run_id for run_id in (restart_run_id, resume_run_id) if run_id}
        busy = [r for r in list_running_runs() if r.get("run_id") not in self_ids]
        if busy:
            raise EvalBusyError(busy)

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
    pre_done: Dict[str, Dict[str, Any]] = {}
    rescore_map: Dict[str, Dict[str, Any]] = {}
    in_place_resume = False

    if restart_run_id:
        source_run = result_store.get_run(restart_run_id)
        if not source_run:
            raise ValueError(f"重来目标 run 不存在: {restart_run_id}")
        if source_run.get("dataset_id") != dataset_id:
            raise ValueError("重来目标 run 与目标测试集不一致")
        if question_id:
            raise ValueError("重来仅支持整体评测")
        # 原地重来：清空旧明细/进度、复用同一条记录，重跑全部题目
        result_store.restart_run_for_retry(restart_run_id, _manifest_with_judge(config_name, judge_config_name, answer_format))
        run_id = restart_run_id
        run_name = source_run.get("run_name") or _generate_run_name(config_name)
        thread = threading.Thread(
            target=_run_suite_thread,
            args=(run_id, dataset_id, questions, override_doc_ids, {}, False,
                  config_name, None, judge_config_name, workers, answer_format),
            daemon=True,
        )
        thread.start()
        return result_store.get_run(run_id) or {"run_id": run_id, "status": "running"}

    if resume_run_id:
        source_run = result_store.get_run(resume_run_id)
        if not source_run:
            raise ValueError(f"续跑源 run 不存在: {resume_run_id}")
        if source_run.get("dataset_id") != dataset_id:
            raise ValueError("续跑源 run 与目标测试集不一致")
        rescore_set = {str(qid) for qid in (rescore_question_ids or [])}
        if rescore_set:
            # 仅对补判题取全量详情（prediction 大字段），其余题维持 light 查询
            rescore_map = {
                str(d.get("question_id") or ""): d["prediction"]
                for d in result_store.list_run_details(resume_run_id)
                if str(d.get("question_id") or "") in rescore_set and d.get("prediction")
            }
        pre_done = {
            str(d.get("question_id") or ""): d
            for d in result_store.list_run_details(resume_run_id, light=True)
            if d.get("status") == "completed" and d.get("scores")
            and str(d.get("question_id") or "") not in rescore_set
        }
        if not pre_done and not rescore_map:
            raise ValueError("续跑源 run 没有可复用的已完成题目")
        # 原地续跑：复用原 run 记录，避免同一轮评测产生两条记录
        result_store.reset_run_for_resume(resume_run_id, _manifest_with_judge(config_name, judge_config_name, answer_format))
        in_place_resume = True
        run_id = resume_run_id
        run_name = source_run.get("run_name") or _generate_run_name(config_name)
    else:
        run_name = _generate_run_name(config_name) if is_full_run else ""
        run_data = result_store.create_run(
            dataset_id, len(questions), run_name=run_name, is_full_run=is_full_run,
            config_snapshot=_manifest_with_judge(config_name, judge_config_name, answer_format),
        )
        run_id = run_data["run_id"]

    thread = threading.Thread(
        target=_run_suite_thread,
        args=(run_id, dataset_id, questions, override_doc_ids, pre_done, in_place_resume,
              config_name, rescore_map, judge_config_name, workers, answer_format),
        daemon=True,
    )
    thread.start()
    return result_store.get_run(run_id) or {"run_id": run_id, "status": "running"}


def _enrich_run_details(
    details: List[Dict[str, Any]],
    dataset_id: str,
    with_question_text: bool = True,
) -> List[Dict[str, Any]]:
    """为运行详情补充题目字段，并按题集顺序（sort_order）排列。

    明细行 id 是建行顺序，不是题目顺序：题目「真正开跑」时 runner 会删行重建
    （见 _run_questions_concurrent._task，状态机如实要求），重建行拿到更大的 id，
    于是按 id 返回会变成「未跑的题排在前面、跑过的题挤到末尾」。前端题号用的是
    数组下标，结果右栏题号与题目列表（题集顺序）整体错位——2026-09-27 用户截图
    实踩：中栏第 3 题（唯一错题）在右栏显示为第 20 格。这里统一按题集顺序返回，
    右栏明细与逐题对比的行号都跟中栏对齐。题集里已不存在的题排在末尾（稳定排序
    保持其相对次序）。

    with_question_text=False（`enrich=0`）时**只保留排序与状态所需字段**：右栏 1040 格
    染色只需要 status/quality，而题干文本占了该载荷的 7 成（1040 题实测 80 KB 里
    约 56 KB 是 1040 份题干）；逐题对比表要用题干时再按需取 enrich=1 那一份。
    """
    if not details:
        return []
    # 只取列表列：补题目元信息用不到 gold，而全量读会把每题的 gold 原文各解析一遍
    # （1040 题集实测 gold 占 1.3 MB，是 get_eval_run 里最大的一块纯浪费）
    questions = result_store.list_questions(dataset_id, summary=True)
    if not with_question_text:
        seq_of = {
            str(question.get("question_id") or ""): idx
            for idx, question in enumerate(questions)
        }
        return sorted(
            details,
            key=lambda d: seq_of.get(str(d.get("question_id") or ""), len(questions)),
        )
    detail_questions = {
        str(question.get("question_id") or ""): question for question in questions
    }
    seq_of = {
        str(question.get("question_id") or ""): idx for idx, question in enumerate(questions)
    }
    enriched = [
        _enrich_detail_with_question(detail, detail_questions.get(str(detail.get("question_id") or ""), {}))
        for detail in details
    ]
    enriched.sort(key=lambda d: seq_of.get(str(d.get("question_id") or ""), len(questions)))
    return enriched


def get_eval_run(
    run_id: str,
    light: bool = False,
    projection: Optional[str] = None,
    enrich: bool = True,
) -> Optional[Dict[str, Any]]:
    """查询运行进度/结果，运行中时实时计算汇总指标。

    light=True 时裁剪 prediction/all_scores/all_predictions 等大字段，
    供列表/轮询场景使用；完整详情通过 get_eval_run_detail 按需获取。
    projection="status" 进一步只取状态染色所需列（去 scores），供题集首屏与轮询；
    展开单题走 get_eval_run_detail，那份仍带分项分数。
    enrich=False 时只补排序（题集顺序），不回传 1040 份题干——右栏格子只染色不用字；
    逐题对比等需要题干的场景显式传 enrich=True。
    """
    run = result_store.get_run(run_id)
    if not run:
        return None
    details = result_store.list_run_details(run_id, light=light, projection=projection)
    result = {**run, "details": details}
    if result.get("details"):
        result["details"] = _enrich_run_details(
            result["details"], run.get("dataset_id") or "", with_question_text=enrich,
        )
    if run.get("status") == "running" and not run.get("summary_scores"):
        completed_details = [d for d in result["details"] if d.get("status") not in ("pending", "running")]
        if completed_details:
            result["summary_scores"] = _compute_summary(completed_details)
    return result


def get_eval_run_detail(run_id: str, question_id: str, light: bool = False) -> Optional[Dict[str, Any]]:
    """获取单道题目的完整运行详情（含 prediction/all_scores/all_predictions）。

    light=True 时裁剪重字段（all_predictions 整块 + prediction 内
    retrieval_debug/retrieved_items/evidences），首屏展开够用；
    完整原文由调用方按需 full 拉取。
    """
    run = result_store.get_run(run_id)
    if not run:
        return None
    detail = result_store.get_run_detail(run_id, question_id, light=light)
    if not detail:
        return None
    return _enrich_run_details([detail], run.get("dataset_id") or "")[0]


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
