"""评分细则评测器（GDP.pdf 类多模态题集）。

与 answer_eval 同链：run_prediction 复用 AnswerEvaluator 的 RAG 问答链（检索→生成），
不重写。差异只在 evaluate：不走单一语义总分，而是拿题目自带的 rubric 逐条判，
headline = 所有 criterion 全过（all_pass，对齐官方 "100% rubrics" 榜），
辅助面 = mean_criteria（通过比例）供分布观测。

金标块结构（eval_question.rubric_gold）：
  {"criteria": [
     {"i":1, "text":"The response should ...", "type":"Primary Intent"|"Dodged Bullet",
      "severity":"Certain dealbreaker"|..., "subjectiveness":"Objective"|"Subjective",
      "implicitness":..., "failure_mode":"Binary"}, ...]}
  - type=Dodged Bullet 的是负向判据（"should avoid X"），满足=没犯 X；判官按语义自然判。
  - 判官温度 0.1（与 answer_eval 同，避免 0 让判分整体偏严）。

反假绿纪律（见 suite_runner._decide_quality）：判官候选链全崩时 score=None、
rubric_fallback=True → quality=None → 计入 skipped，绝不拿 0 分或检索分顶成 correct。
"""
import json
import time
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner.answer_eval import (
    AnswerEvaluator,
    _resolve_judge_candidates,
    is_refusal,
)
from evals_core.runner.base import register_evaluator

RUBRIC_SYSTEM_PROMPT = (
    "你是严格、保守的答案评分器。给定一个用户问题、一份待评回答、以及一组编号的评分细则（rubric）。"
    "逐条判断该回答是否满足每条细则，只做二元 pass/fail，不要给分数。"
    "每条细则都是对回答的一项要求：正向条目（Primary Intent）要求回答包含/答对指定内容才算满足；"
    "负向条目（Dodged Bullet）通常表述为『回答应避免某错误』，只要回答没有犯该错误即算满足。"
    "只要回答与某条细则存在任何偏差、遗漏、数值错误或不确定，该条判 fail。"
    "严格只输出 JSON，不要任何额外文字。"
)

RUBRIC_EVAL_PROMPT = """\
# 用户问题
{question}

# 待评回答
{answer}

# 评分细则（共 {n} 条）
{criteria_block}

# 输出格式（严格 JSON）
{{"results": [{{"index": <1..{n} 的整数>, "pass": <true 或 false>, "reason": "<不超过 40 字的判定依据>"}}]}}
必须为每一条细则都产出一个结果，index 从 1 连续到 {n}。"""


def _build_criteria_block(criteria: List[Dict[str, Any]]) -> str:
    # 批内局部编号 1..k（跨批由 offset 映射回全局），避免判官在长清单上串号
    lines = []
    for idx, c in enumerate(criteria, 1):
        text = str(c.get("text") or c.get("criterion") or "").strip()
        ctype = str(c.get("type") or "").strip()
        sev = str(c.get("severity") or "").strip()
        meta = "｜".join(x for x in (ctype, sev) if x)
        lines.append(f"{idx}. {text}" + (f" [{meta}]" if meta else ""))
    return "\n".join(lines)


def _judge_rubric_batch(
    question_text: str,
    answer: str,
    batch: List[Dict[str, Any]],
    offset: int,
    judge_config_name: Optional[str] = None,
) -> Dict[str, Any]:
    """判一批（局部 1..k 编号），结果按全局序号 offset+局部 回写。单批判官失败→fallback=True（不抛）。"""
    from ai_inference.llm_client import chat_result_guarded, get_llm_client
    from ai_inference.llm_response_parser import extract_json_from_text, ParseError

    n = len(batch)
    prompt = RUBRIC_EVAL_PROMPT.format(
        question=question_text, answer=answer, n=n, criteria_block=_build_criteria_block(batch)
    )
    messages = [
        {"role": "system", "content": RUBRIC_SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]
    t_start = time.time()
    client = get_llm_client()
    candidates = _resolve_judge_candidates(judge_config_name)
    last_exc: Optional[Exception] = None
    for index, config_name in enumerate(candidates):
        try:
            result = chat_result_guarded(
                client, messages, mode="instruct", config_name=config_name, temperature=0.1
            )
            raw = result.text
            try:
                parsed = extract_json_from_text(raw, strict=True)
            except ParseError:
                parsed = extract_json_from_text(raw, strict=False)
            rows = parsed.get("results") if isinstance(parsed, dict) else None
            if not isinstance(rows, list):
                raise ParseError(f"判官未返回 results 列表: {str(raw)[:200]}")
            results: Dict[int, Dict[str, Any]] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    local = int(row.get("index"))
                except (TypeError, ValueError):
                    continue
                if not (1 <= local <= n):
                    continue
                results[offset + local] = {
                    "pass": bool(row.get("pass")),
                    "reason": str(row.get("reason", "")).strip(),
                }
            return {
                "results": results,
                "judge_used": config_name or "<被测默认>",
                "judge_failover": index > 0,
                "evaluated": True,
                "fallback": False,
                "error": "",
                "eval_duration": round(time.time() - t_start, 2),
            }
        except Exception as exc:  # noqa: BLE001 —— 单候选失败切下一候选
            from angineer_core.base_utils import is_fatal_exception

            if is_fatal_exception(exc):
                raise
            last_exc = exc
    return {
        "results": {},
        "judge_used": None,
        "judge_failover": False,
        "evaluated": False,
        "fallback": True,
        "error": f"批判官失败（候选 {len(candidates)} 端点均失败）: {last_exc}",
        "eval_duration": round(time.time() - t_start, 2),
    }


def _judge_rubric(
    question_text: str,
    answer: str,
    criteria: List[Dict[str, Any]],
    judge_config_name: Optional[str] = None,
) -> Dict[str, Any]:
    """分批判完整份 rubric 并合并（全局序号键）。长清单一次判易超时→按批切小、逐批判。

    批次大小 env GDP_RUBRIC_BATCH（默认 8）。仅当所有批都失败才整体 fallback；
    部分批失败时缺失条目按 fail 计（保守），并标记 partial_batches_failed 供观测。
    """
    import os

    try:
        batch_size = int(os.getenv("GDP_RUBRIC_BATCH", "8"))
    except (TypeError, ValueError):
        batch_size = 8
    batch_size = max(1, batch_size)
    total = len(criteria)
    merged: Dict[int, Dict[str, Any]] = {}
    all_fallback = True
    any_failover = False
    judge_used: Optional[str] = None
    durations: List[float] = []
    errors: List[str] = []
    n_batches = 0
    n_failed_batches = 0
    for start in range(0, total, batch_size):
        batch = criteria[start : start + batch_size]
        r = _judge_rubric_batch(question_text, answer, batch, offset=start, judge_config_name=judge_config_name)
        merged.update(r["results"])
        durations.append(r.get("eval_duration", 0))
        n_batches += 1
        if r["fallback"]:
            n_failed_batches += 1
            errors.append(f"批{start//batch_size+1}:{r['error']}")
        else:
            all_fallback = False
            if r.get("judge_used") and judge_used is None:
                judge_used = r["judge_used"]
            any_failover = any_failover or r.get("judge_failover", False)
    return {
        "results": merged,
        "judge_used": judge_used,
        "judge_failover": any_failover,
        "evaluated": not all_fallback,
        "fallback": all_fallback,
        "error": ";".join(errors) if errors else "",
        "eval_duration": round(sum(durations), 2),
        "n_batches": n_batches,
        "n_failed_batches": n_failed_batches,
        "partial_batches_failed": 0 < n_failed_batches < n_batches,
    }


def run_rubric_item(
    question_text: str, answer: str, rubric: Dict[str, Any], judge_config_name: Optional[str] = None
) -> Dict[str, Any]:
    """对单题跑 rubric 判分，返回逐条结果与两级指标。

    judge_config_name：run 级判官选择（与 answer_eval 同口径，来自题集/UI 弹框），
    空则走默认判官候选链——想贴官方数就传官方判官配置名。
    """
    criteria = [c for c in (rubric or {}).get("criteria", []) if isinstance(c, dict)]
    n_total = len(criteria)
    if n_total == 0:
        # 金标缺失必须响亮失败（与 intent_eval 同纪律），否则空 rubric 会 all_pass=真 假绿
        return {
            "status": "NO_GOLD",
            "n_total": 0,
            "n_pass": 0,
            "all_pass": False,
            "mean_criteria": 0.0,
            "per_criterion": [],
        }
    stripped = (answer or "").strip()
    empty = not stripped
    if empty:
        # 真空答案：无从可判，全条 fail（不烧判官调用）。半拒答（有内容）仍走判官，
        # 让 Dodged Bullet 负向判据可按语义通过（拒答确实没犯错），更贴官方逐条判口径。
        judged = {"results": {}, "evaluated": True, "fallback": False, "judge_used": "<空答案短路>", "judge_failover": False, "error": "", "eval_duration": 0.0}
    else:
        judged = _judge_rubric(question_text, answer, criteria, judge_config_name=judge_config_name)
    if judged["fallback"]:
        return {
            "status": "JUDGE_FALLBACK",
            "n_total": n_total,
            "n_pass": 0,
            "all_pass": False,
            "mean_criteria": None,
            "per_criterion": [],
            "error": judged["error"],
        }
    per: List[Dict[str, Any]] = []
    n_pass = 0
    dealbreaker_total = dealbreaker_pass = 0
    for idx, c in enumerate(criteria, 1):
        r = judged["results"].get(idx, {"pass": False, "reason": "判官缺该条结果"})
        passed = bool(r["pass"])
        n_pass += 1 if passed else 0
        if str(c.get("severity") or "") == "Certain dealbreaker":
            dealbreaker_total += 1
            dealbreaker_pass += 1 if passed else 0
        per.append({
            "i": idx,
            "type": str(c.get("type") or ""),
            "severity": str(c.get("severity") or ""),
            "subjectiveness": str(c.get("subjectiveness") or ""),
            "text": str(c.get("text") or c.get("criterion") or ""),
            "pass": passed,
            "reason": r["reason"],
        })
    all_pass = n_pass == n_total
    return {
        "status": "PASS" if all_pass else ("EMPTY" if empty else ("REFUSAL" if is_refusal(stripped) else "PARTIAL")),
        "n_total": n_total,
        "n_pass": n_pass,
        "all_pass": all_pass,
        "mean_criteria": round(n_pass / n_total, 4),
        "dealbreaker_pass": dealbreaker_pass,
        "dealbreaker_total": dealbreaker_total,
        "per_criterion": per,
        "judge_used": judged["judge_used"],
        "judge_failover": judged["judge_failover"],
        "n_batches": judged.get("n_batches", 1),
        "n_failed_batches": judged.get("n_failed_batches", 0),
        "partial_batches_failed": judged.get("partial_batches_failed", False),
    }


class RubricEvaluator(AnswerEvaluator):
    """评分细则题评测器：复用 RAG 问答链生成答案，evaluate 逐条判 rubric。"""

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        rubric = gold or question.get("rubric_gold") or {}
        answer = str(prediction.get("answer") or "").strip()
        question_text = str(question.get("question") or "")
        judge_config_name = str(question.get("judge_config_name") or "").strip() or None
        outcome = run_rubric_item(question_text, answer, rubric, judge_config_name=judge_config_name)
        # quality 映射：all_pass→1.0（correct），其余→0.0（wrong）；
        # 判官崩→score=None（quality None→skipped，不假绿，见 _decide_quality）。
        if outcome["status"] == "JUDGE_FALLBACK":
            score: Optional[float] = None
        elif outcome["status"] == "NO_GOLD":
            score = None
        else:
            score = 1.0 if outcome["all_pass"] else 0.0
        result = {
            "evaluated": outcome["status"] not in ("JUDGE_FALLBACK", "NO_GOLD"),
            "score": score,
            "rubric_status": outcome["status"],
            "n_total": outcome["n_total"],
            "n_pass": outcome["n_pass"],
            "all_pass": outcome["all_pass"],
            "mean_criteria": outcome["mean_criteria"],
            "refusal": is_refusal(answer) if answer else True,
        }
        for k in ("dealbreaker_pass", "dealbreaker_total", "judge_used", "judge_failover", "per_criterion", "error",
                  "n_batches", "n_failed_batches", "partial_batches_failed"):
            if k in outcome:
                result[k] = outcome[k]
        # 观测标注随 prediction 落库（与 answer_eval 同口径，缺省=旧 prediction 复用）
        if prediction.get("final_outcome"):
            result["final_outcome"] = str(prediction["final_outcome"])
        try:
            result["llm_error_count"] = int(prediction.get("llm_error_count") or 0)
        except (TypeError, ValueError):
            result["llm_error_count"] = 0
        return result


register_evaluator("rubric", RubricEvaluator)
