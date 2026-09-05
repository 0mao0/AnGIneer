"""客户端异常题分类（evals_core.runner.anomaly 的纯 dict 镜像）。

与服务器侧规则逐字对齐（改一侧必须同步另一侧，两侧都有单测钉住）：
- judge_fail：answer 分 semantic_fallback=True（基础设施失败，不是模型失败）
- exec_error：status=error 或 error 非空
- slow：latency_ms 超阈值，仅观察单
- 规则判零（拒答等确定性 0 分）**不是异常**：semantic_evaluated=False 且
  semantic_fallback=False，重跑必然同样结果。

为何不直接 import evals_core：scripts 面向已落盘的 raw json / API 返回离线分析，
不应把整套引擎依赖拖进评测脚本链路。
"""
import json
from typing import Any, Dict, List

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
    merged = dict(_as_dict(detail.get("scores")))
    merged.update({
        k: v for k, v in _as_dict(_as_dict(detail.get("all_scores")).get("answer")).items()
        if v is not None
    })
    return merged


def classify_detail(detail: Dict[str, Any], slow_ms: int = DEFAULT_SLOW_MS) -> List[str]:
    types: List[str] = []
    if str(detail.get("status") or "") == "error" or str(detail.get("error") or "").strip():
        types.append(EXEC_ERROR)
    if answer_section(detail).get("semantic_fallback") is True:
        types.append(JUDGE_FAIL)
    latency = detail.get("latency_ms")
    if isinstance(latency, (int, float)) and latency >= slow_ms:
        types.append(SLOW)
    return types


def detect(details: List[Dict[str, Any]], slow_ms: int = DEFAULT_SLOW_MS) -> Dict[str, List[str]]:
    """返回 {异常类型: [question_id]}；slow 恒列出（可为空），异常类型无命中不出现。"""
    result: Dict[str, List[str]] = {SLOW: []}
    for d in details:
        qid = str(d.get("question_id") or "")
        for t in classify_detail(d, slow_ms=slow_ms):
            result.setdefault(t, []).append(qid)
    return result


def actionable(anomalies: Dict[str, List[str]]) -> Dict[str, List[str]]:
    """需要重试处理的异常（judge_fail + exec_error），排除仅观察的 slow。"""
    return {k: v for k, v in anomalies.items() if k in (JUDGE_FAIL, EXEC_ERROR) and v}
