"""异常题检测：把逐题结果分为 judge_fail / exec_error / slow 观察单。

分类纪律（2026-09-05 评测实踩，勿改宽）：
- 规则判零（该答却拒答、无 gold 拒答判定等）semantic_evaluated=False 但
  semantic_fallback=False 且 reason 确定——**不是异常**，重跑必然同样结果；
- judge_fail：judge 全候选链失败（answer 分 semantic_fallback=True）。
  这是基础设施失败不是模型失败，按 0 分混进 overall 会系统性压低分数；
- exec_error：status='error' 或 error 非空（问答链路执行异常/超时止损）；
- slow：latency_ms 超阈值仅列观察单，不强制重跑（并发排队也会推高 latency）。

本模块为纯函数（不 import 引擎），run 详情 dict 的 scores/all_scores
允许是 JSON 字符串或已解析 dict（result_store 原始行 vs API 返回两种形态）。
"""
import json
from typing import Any, Dict, List, Optional

JUDGE_FAIL = "judge_fail"
EXEC_ERROR = "exec_error"
SLOW = "slow"

DEFAULT_SLOW_MS = 120_000


def _as_dict(value: Any) -> Dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (ValueError, TypeError):
            return {}
    return {}


def answer_section(detail: Dict[str, Any]) -> Dict[str, Any]:
    """合并 answer 评判字段：primary scores 即 answer 时直接在顶层，否则在 all_scores.answer。"""
    merged = dict(_as_dict(detail.get("scores")))
    merged.update({k: v for k, v in _as_dict(_as_dict(detail.get("all_scores")).get("answer")).items() if v is not None})
    return merged


def classify_detail(detail: Dict[str, Any], slow_ms: int = DEFAULT_SLOW_MS) -> List[str]:
    """返回该题命中的异常类型列表（可为空 = 正常）。"""
    types: List[str] = []
    if str(detail.get("status") or "") == "error" or str(detail.get("error") or "").strip():
        types.append(EXEC_ERROR)
    answer = answer_section(detail)
    if answer.get("semantic_fallback") is True:
        types.append(JUDGE_FAIL)
    latency = detail.get("latency_ms")
    if isinstance(latency, (int, float)) and latency >= slow_ms:
        types.append(SLOW)
    return types


def detect_anomalies(details: List[Dict[str, Any]], slow_ms: int = DEFAULT_SLOW_MS) -> Dict[str, List[str]]:
    """返回 {异常类型: [question_id, ...]}，无命中的类型不出现（slow 除外恒列出）。"""
    result: Dict[str, List[str]] = {SLOW: []}
    for d in details:
        qid = str(d.get("question_id") or "")
        for t in classify_detail(d, slow_ms=slow_ms):
            result.setdefault(t, []).append(qid)
    return result


def judge_failed_count(details: List[Dict[str, Any]]) -> int:
    """run 汇总用：judge 全链失败的题数（按 question_id 去重）。"""
    seen = set()
    count = 0
    for d in details:
        qid = str(d.get("question_id") or "")
        if qid in seen:
            continue
        seen.add(qid)
        if JUDGE_FAIL in classify_detail(d, slow_ms=-1):  # slow_ms=-1：只看异常不看慢
            count += 1
    return count
