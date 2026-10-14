# -*- coding: utf-8 -*-
"""判官双判一致制（judge agreement protocol）——开关默认关，零行为变更。

背景（2026-10-14/15 reviewed-exam 两轮实测）：同一份答案两次判分跨阈翻转（sem
1.0↔0.2 这类全域跳动），单跑总分被判官抖动支配（±3~7 题），小改动净效测不出。

协议（``ANGINEER_JUDGE_REJUDGE=1`` 时启用，legacy/deepeval 两条判分链共用）：
- 判第一票、第二票；两票过阈结论一致 → 收口（共 2 次判分）；
- 结论不一致 → 加判第三票，多数表决收口（共 3 次判分）；
- 第二/第三票判分链路失败 → 退回已有票的稳妥口径并留痕（mode=second_failed /
  split_fallback），不让重判把有效结果变失败。

留痕：scores（各票原始分）、votes（各票过阈结论）、mode 写入 ``semantic_rejudge``
字段，随 eval_run_detail 落库供审计与后续定基。语义分输出 = 各票中位数（偶数票取
中间两票均值）。成本：基线 2× 判分调用；两票不一致的题 3×。
"""
import os
from typing import Any, Dict, List, Optional


ENV_SWITCH = "ANGINEER_JUDGE_REJUDGE"


def rejudge_enabled() -> bool:
    """双判一致制开关（默认关；=1/true/on 启用）。"""
    return (os.getenv(ENV_SWITCH, "0") or "0").strip().lower() in ("1", "true", "on")


def median_score(scores: List[float]) -> float:
    """各票原始分中位数（偶数票取中间两票均值；空列表由调用方保证不发生）。"""
    ordered = sorted(float(s) for s in scores)
    n = len(ordered)
    if n == 0:
        raise ValueError("median_score 需要至少一票")
    mid = n // 2
    if n % 2 == 1:
        return round(ordered[mid], 4)
    return round((ordered[mid - 1] + ordered[mid]) / 2, 4)


def combine_votes(votes: List[bool], scores: List[float], threshold: float) -> Dict[str, Any]:
    """过阈结论合并：双一致→收口；三票→多数；两票分歧缺第三票→均值过阈兜底。"""
    if len(votes) >= 2 and votes[0] == votes[1]:
        return {"passed": bool(votes[0]), "mode": "double_agree"}
    if len(votes) >= 3:
        return {"passed": sum(1 for v in votes[:3] if v) >= 2, "mode": "majority"}
    avg = sum(float(s) for s in scores) / max(1, len(scores))
    return {"passed": avg >= threshold, "mode": "split_fallback"}


def build_audit(scores: List[float], votes: List[bool], mode: str) -> Dict[str, Any]:
    """semantic_rejudge 留痕结构（随 scores 落库）。"""
    return {"scores": list(scores), "votes": [bool(v) for v in votes], "mode": mode}
