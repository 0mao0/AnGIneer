"""回答评测器，通过 query_engine 直接调用回答链路。"""
import json
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator
from evals_core.runner._prediction_trace import enrich_prediction_trace
from evals_core.runner._query_helper import run_eval_query
from evals_core.runner.retrieval_eval import normalize_section_path
from angineer_core.base_utils import is_fatal_exception

DEFAULT_SEMANTIC_THRESHOLD = 0.65

_SEMANTIC_EVAL_PROMPT = """\
你是评测助手。判断"系统答案"是否在语义上等价于或包含了"标准答案"的核心信息。

标准答案：{gold_answer}
{keyword_hint}系统答案：{system_answer}

评分标准：
- 1.0：系统答案完整包含标准答案的核心信息，语义等价
- 0.7-0.9：系统答案包含大部分核心信息，但有少量遗漏或不精确
- 0.4-0.6：系统答案包含部分核心信息，但有明显遗漏或偏差
- 0.0-0.3：系统答案与标准答案核心信息不符或缺失严重

返回 JSON：{{"score": 0.0~1.0, "reason": "简短说明"}}"""


def normalize_eval_text(value: str) -> str:
    """归一化评测文本，便于做关键词断言。"""
    normalized = str(value or "")
    normalized = normalized.replace("（", "(").replace("）", ")")
    normalized = normalized.replace("，", ",").replace("。", ".").replace("：", ":")
    normalized = normalized.replace("；", ";").replace("～", "~").replace("％", "%")
    normalized = normalized.lower()
    compact_chars: List[str] = []
    for char in normalized:
        if char.isspace():
            continue
        if char.isalnum() or "\u4e00" <= char <= "\u9fff" or char in {".", "%", "~", "=", "+", "-", "<", ">", "(", ")", ":", "/"}:
            compact_chars.append(char)
    return "".join(compact_chars)


def evaluate_correctness_check(answer: str, check: Dict[str, Any]) -> bool:
    """判断答案是否满足单条结构化正确性断言。"""
    check_type = str(check.get("type") or "").strip()
    keywords = [normalize_eval_text(str(item)) for item in check.get("keywords", []) if str(item).strip()]
    normalized_answer = normalize_eval_text(answer)
    if not check_type or not keywords:
        return True
    if check_type == "contains_all":
        return all(keyword in normalized_answer for keyword in keywords)
    if check_type == "contains_any":
        return any(keyword in normalized_answer for keyword in keywords)
    return True


def is_refusal(answer: str) -> bool:
    """判断回答是否触发系统默认拒答。"""
    normalized = (answer or "").strip()
    refusal_markers = (
        "没有检索到足够证据",
        "建议缩小文档范围",
        "换一种问法",
    )
    return any(marker in normalized for marker in refusal_markers)


def _build_keyword_hint(checks: List[Dict[str, Any]]) -> str:
    """从 correctness_checks 中提取关键词，拼接为 prompt 提示行。"""
    all_keywords: List[str] = []
    for check in checks:
        for kw in check.get("keywords", []):
            kw_str = str(kw).strip()
            if kw_str and kw_str not in all_keywords:
                all_keywords.append(kw_str)
    if not all_keywords:
        return ""
    return f"关键词提示：{', '.join(all_keywords)}\n"


def _build_gold_answer(gold_answer: str, checks: List[Dict[str, Any]]) -> str:
    """构建 LLM 评判用的标准答案文本。"""
    if gold_answer and gold_answer.strip():
        return gold_answer.strip()
    all_keywords: List[str] = []
    for check in checks:
        for kw in check.get("keywords", []):
            kw_str = str(kw).strip()
            if kw_str and kw_str not in all_keywords:
                all_keywords.append(kw_str)
    if all_keywords:
        return f"（无标准答案文本，关键词要点：{', '.join(all_keywords)}）"
    return "（无标准答案）"


def _llm_semantic_evaluate(
    answer: str,
    gold_answer: str,
    checks: List[Dict[str, Any]],
    semantic_threshold: float,
) -> Dict[str, Any]:
    """调用 LLM 对系统答案做语义评判，返回评分与理由。"""
    import time as _time
    from ai_inference.llm_client import get_llm_client
    from ai_inference.llm_response_parser import extract_json_from_text, ParseError

    built_gold = _build_gold_answer(gold_answer, checks)
    keyword_hint = _build_keyword_hint(checks)
    prompt = _SEMANTIC_EVAL_PROMPT.format(
        gold_answer=built_gold,
        keyword_hint=keyword_hint,
        system_answer=answer,
    )
    messages = [
        {"role": "system", "content": "你是一个严格的评测助手，只返回 JSON 格式的评分结果。"},
        {"role": "user", "content": prompt},
    ]
    try:
        _t_start = _time.time()
        client = get_llm_client()
        raw_response = client.chat(messages, mode="instruct", config_name="Qwen3.6-35B-A3B (Private)")
        eval_duration = round(_time.time() - _t_start, 2)
        parsed = extract_json_from_text(raw_response)
        score = float(parsed.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reason = str(parsed.get("reason", "")).strip()
        passed = score >= semantic_threshold
        return {
            "semantic_score": round(score, 4),
            "semantic_reason": reason,
            "semantic_evaluated": True,
            "semantic_fallback": False,
            "semantic_passed": passed,
            "eval_duration": eval_duration,
        }
    except Exception as exc:
        if is_fatal_exception(exc):
            raise
        return {
            "semantic_score": None,
            "semantic_reason": f"LLM 语义评判失败: {exc}",
            "semantic_evaluated": False,
            "semantic_fallback": True,
            "semantic_passed": None,
        }


def citations_match_section_paths(citations: List[Dict[str, Any]], gold_section_paths: List[str]) -> bool:
    """判断引用中是否覆盖 gold 的章节路径要求。"""
    normalized_gold_paths = [normalize_section_path(item) for item in gold_section_paths if normalize_section_path(item)]
    if not normalized_gold_paths:
        return True
    normalized_citation_paths = [
        normalize_section_path(str(item.get("section_path") or ""))
        for item in citations
        if normalize_section_path(str(item.get("section_path") or ""))
    ]
    for citation_path in normalized_citation_paths:
        if any(
            citation_path == gold_path or citation_path.endswith(gold_path) or gold_path in citation_path
            for gold_path in normalized_gold_paths
        ):
            return True
    return False


class AnswerEvaluator(BaseEvaluator):
    """回答评测器，通过 query_engine 直接调用回答链路。"""

    @staticmethod
    def _emit_enriched_stage(
        question: Dict[str, Any],
        partial: Dict[str, Any],
        stage_callback: Optional[Callable[[Dict[str, Any]], None]],
    ) -> None:
        """把 dispatcher 中间态归一化后回传给评测轮询层。"""
        if not stage_callback:
            return
        prediction = {
            "answer": partial.get("answer", ""),
            "citations": list(partial.get("citations") or []),
            "retrieved_items": list(partial.get("retrieved_items") or []),
            "task_type": partial.get("task_type", ""),
            "strategy": partial.get("strategy", ""),
            "system_prompt": partial.get("system_prompt", ""),
            "retrieval_debug": partial.get("retrieval_debug", {}),
            "stage_timings": partial.get("stage_timings", {}),
            "intent": partial.get("intent", {}),
            "stage": partial.get("stage", ""),
        }
        stage_callback(enrich_prediction_trace(question, partial, prediction))

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable[[Dict[str, Any]], None]] = None) -> Dict[str, Any]:
        """通过 query_engine 直接调用回答链路，支持渐进式阶段回调。"""
        question_id = str(question.get("question_id") or "")
        query = str(question.get("question") or "").strip()
        if not query:
            return {}

        if stage_callback:
            stage_callback({
                "answer": "",
                "stage": "intent",
                "stage_timings": {},
                "intent": {},
            })

        data = run_eval_query(
            query=query,
            library_id=str(question.get("library_id") or "default"),
            doc_ids=list(question.get("doc_ids") or []),
            session_id=f"eval-{question_id}",
            stage_callback=(lambda partial: self._emit_enriched_stage(question, partial, stage_callback)) if stage_callback else None,
        )

        if "error" in data:
            return {"error": data["error"]}

        prediction = {
            "answer": data.get("answer", ""),
            "citations": list(data.get("citations") or []),
            "confidence": data.get("confidence", 0.0),
            "retrieved_items": list(data.get("retrieved_items") or []),
            "task_type": data.get("task_type", ""),
            "strategy": data.get("strategy", ""),
            "debug": data.get("debug", {}),
            "thinking": data.get("queryChain", ""),
            "system_prompt": data.get("system_prompt", ""),
            "retrieval_debug": data.get("retrieval_debug", {}),
            "stage_timings": data.get("stage_timings", {}),
            "intent": data.get("intent", {}),
        }
        result = enrich_prediction_trace(question, data, prediction)

        if stage_callback:
            stage_callback(result)

        return result

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        """计算回答评测指标，使用 LLM 作为主判，关键词作为 prompt 提示。"""
        answer = str(prediction.get("answer") or "").strip()
        citations = list(prediction.get("citations") or [])
        checks = [item for item in gold.get("correctness_checks", []) if isinstance(item, dict)]
        gold_answer = str(gold.get("gold_answer") or "").strip()
        semantic_threshold = DEFAULT_SEMANTIC_THRESHOLD
        must_cite_section_paths = [str(item) for item in gold.get("must_cite_section_paths", []) if item]
        if not must_cite_section_paths:
            must_cite_section_paths = [str(item) for item in gold.get("gold_section_paths", []) if item]
        refusal_expected = bool(gold.get("refusal_expected", False))
        actual_refusal = is_refusal(answer)
        citation_ok = citations_match_section_paths(citations, must_cite_section_paths) if must_cite_section_paths else True

        if not answer:
            return {
                "score": 0.0,
                "evaluated": True,
                "has_answer": False,
                "citation_ok": citation_ok,
                "refusal_correct": refusal_expected == actual_refusal,
                "correctness_checked": False,
                "semantic_evaluated": False,
            }

        if refusal_expected:
            if actual_refusal:
                return {
                    "score": 1.0,
                    "evaluated": True,
                    "has_answer": True,
                    "citation_ok": citation_ok,
                    "refusal_correct": True,
                    "correctness_checked": False,
                    "semantic_evaluated": False,
                }
            else:
                return {
                    "score": 0.0,
                    "evaluated": True,
                    "has_answer": True,
                    "citation_ok": citation_ok,
                    "refusal_correct": False,
                    "correctness_checked": False,
                    "semantic_evaluated": False,
                }

        if not gold_answer and not checks:
            if not citation_ok:
                score = 0.0
            else:
                score = 1.0
            return {
                "score": score,
                "evaluated": True,
                "has_answer": True,
                "citation_ok": citation_ok,
                "refusal_correct": refusal_expected == actual_refusal,
                "correctness_checked": False,
                "semantic_evaluated": False,
            }

        keyword_check_details = [
            {
                "type": check.get("type"),
                "keywords": check.get("keywords", []),
                "passed": evaluate_correctness_check(answer, check),
            }
            for check in checks
        ]
        failed_checks = [check for check in checks if not evaluate_correctness_check(answer, check)]
        keyword_score = 1.0 if not failed_checks else 0.0

        semantic_result = _llm_semantic_evaluate(answer, gold_answer, checks, semantic_threshold)

        if semantic_result["semantic_evaluated"]:
            semantic_score = semantic_result["semantic_score"]
            correctness_score = semantic_score
            overall_score = 1.0 if semantic_result["semantic_passed"] else 0.0
        else:
            correctness_score = keyword_score
            overall_score = keyword_score

        result = {
            "score": overall_score,
            "evaluated": True,
            "has_answer": True,
            "citation_ok": citation_ok,
            "refusal_correct": refusal_expected == actual_refusal,
            "correctness_checked": True,
            "correctness_score": correctness_score,
            "failed_checks": failed_checks,
            "check_details": keyword_check_details,
            "semantic_score": semantic_result["semantic_score"],
            "semantic_reason": semantic_result["semantic_reason"],
            "semantic_evaluated": semantic_result["semantic_evaluated"],
            "semantic_fallback": semantic_result["semantic_fallback"],
            "semantic_passed": semantic_result["semantic_passed"],
            "semantic_threshold": semantic_threshold,
        }
        return result


register_evaluator("answer", AnswerEvaluator)
