# -*- coding: utf-8 -*-
"""意图路由评测器：题目带 intent 金标块时只断言分类器产出的路由结果，不跑检索/生成/判官。

真相源说明（2026-09-29）：与 probe_eval 同构。分类器由宿主（aichat-api）在启动时经
set_intent_classifier() 注入，evals-core 不依赖 angineer-core；未注入时 intent 题直接报错，
不静默跳过。

断言面（三级，route 恒为致命项）：
  ① route  —— 生产路由桶命中（agent_policy.build_attempts 实际优先级）【致命】
     route 由 (level, mode) 派生，是生产真正消费的东西：同桶的 L3↔L4 混淆不改注入工具、
     不影响链路，故默认不记错。
  ② level  —— 意图层级命中；仅当金标 strict_level=true 才致命
  ③ mode   —— 服务模式命中；仅当金标 strict_mode=true 才致命

xfail 语义（与 probe_eval 一致）：致命项挂 = 已知缺口仍在（XFAIL-OK，记 correct）；
全过 = 缺口已修（XPASS，记 correct 并提示摘除 xfail 标记）。

金标块结构（eval_question.intent_gold）：
  {"level": "L2", "mode": "structured_lookup", "route": "L2",
   "family": "L2_clause_number", "trap": "问条款出处而非内容",
   "rationale": "分类法规则 3：应符合哪条 + 无计算 = L2",
   "strict_level": false, "strict_mode": false, "xfail": false}
route 缺省时按 level/mode 现场派生，避免金标与派生规则漂移。
"""
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator

# 生产路由桶（镜像 agent_policy.build_attempts 的判定顺序，改那边必须同步这里）
ROUTE_L0 = "L0"
ROUTE_L1 = "L1"
ROUTE_META = "meta"  # legacy：历史 run 记录含 service_mode="meta_query"，删映射会追溯改写历史分布（新流量不再产生）
ROUTE_L2 = "L2"
ROUTE_COMPLEX = "complex"

_intent_classifier: Optional[Callable[..., Any]] = None


def set_intent_classifier(fn: Optional[Callable[..., Any]]) -> None:
    """注入生产意图分类函数（签名兼容 IntentClassifier.classify_intent(query)）。

    返回值可用性口径：需带 intent_level / service_mode 属性（IntentResult 契约）。
    """
    global _intent_classifier
    _intent_classifier = fn


def derive_route(level: Any, mode: Any) -> str:
    """由 (level, service_mode) 派生生产路由桶。与 agent_policy.build_attempts 同序。"""
    lv = str(level or "")
    md = str(mode or "")
    if md == "meta_query":
        return ROUTE_META
    if lv == "L0" or md == "casual_chat":
        return ROUTE_L0
    if lv in ("L3", "L4") or md in ("standard_sop", "dynamic_orchestration"):
        return ROUTE_COMPLEX
    if lv == "L2" or md in ("structured_lookup", "sql_first"):
        return ROUTE_L2
    return ROUTE_L1


def _fatal_checks(probe: Dict[str, Any]) -> List[str]:
    fatal = ["route"]
    if probe.get("strict_level"):
        fatal.append("level")
    if probe.get("strict_mode"):
        fatal.append("mode")
    return fatal


def run_intent_item(item: Dict[str, Any], predicted: Dict[str, Any]) -> Dict[str, Any]:
    """对单题的路由结果跑断言，返回 checks/failed/fatal_failed/status。

    item 需带 intent 金标块；predicted = {"level": ..., "mode": ..., "route": ...}。
    """
    probe = item.get("intent") or item.get("intent_gold") or {}
    gold_level = str(probe.get("level") or "")
    gold_mode = str(probe.get("mode") or "")
    gold_route = str(probe.get("route") or "") or derive_route(gold_level, gold_mode)
    xfail = bool(probe.get("xfail"))

    # 金标缺失必须响亮失败：空金标派生出的 L1 会与「模型默认也答 L1」撞成假绿。
    # 与 probe_eval「未注入就报错、不静默跳过」同纪律。
    if not probe:
        return {
            "checks": {"gold": "金标块为空（intent / intent_gold 均缺失）"},
            "failed": ["gold"],
            "fatal_failed": ["gold"],
            "status": "FAIL",
            "xfail": xfail,
            "gold_route": gold_route,
            "got_route": derive_route(probe.get("level") or predicted.get("level"),
                                      probe.get("mode") or predicted.get("mode")),
            "family": "",
            "trap": "",
        }

    got_level = str(predicted.get("level") or "")
    got_mode = str(predicted.get("mode") or "")
    got_route = str(predicted.get("route") or "") or derive_route(got_level, got_mode)

    checks: Dict[str, str] = {
        "route": "ok" if got_route == gold_route else f"期望 {gold_route} 实际 {got_route}",
        "level": "ok" if got_level == gold_level else f"期望 {gold_level} 实际 {got_level}",
        "mode": "ok" if got_mode == gold_mode else f"期望 {gold_mode} 实际 {got_mode}",
    }
    failed = [k for k, v in checks.items() if v != "ok"]
    fatal = _fatal_checks(probe)
    fatal_failed = [k for k in failed if k in fatal]

    if xfail:
        status = "XFAIL-OK" if fatal_failed else "XPASS(请摘xfail)"
    else:
        status = "FAIL" if fatal_failed else "PASS"
    return {
        "checks": checks,
        "failed": failed,
        "fatal_failed": fatal_failed,
        "status": status,
        "xfail": xfail,
        "gold_route": gold_route,
        "got_route": got_route,
        "family": probe.get("family") or "",
        "trap": probe.get("trap") or "",
    }


class IntentEvaluator(BaseEvaluator):
    """意图路由题评测器：run_prediction 只跑分类器，evaluate 跑路由断言。"""

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable] = None) -> Dict[str, Any]:
        if _intent_classifier is None:
            return {"error": "intent 评测器未注入分类函数（宿主启动需调 intent_eval.set_intent_classifier）"}
        result = _intent_classifier(str(question.get("question") or ""))
        level = getattr(result, "intent_level", None)
        mode = getattr(result, "service_mode", None)
        prediction = {
            "level": level,
            "mode": mode,
            "route": derive_route(level, mode),
            "intent_type": getattr(result, "intent_type", None),
            "reason": getattr(result, "reason", None),
            "probe_mode": "classify_only",
        }
        if stage_callback:
            stage_callback(prediction)
        return prediction

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        probe = gold or question.get("intent_gold") or {}
        outcome = run_intent_item({"intent": probe}, prediction)
        # quality 映射走 _decide_quality 的 score 阈值：致命项挂 → 0.0（<0.8 → wrong），
        # PASS/XFAIL-OK/XPASS → 1.0（xfail 挂账题按预期失败记过，与 probe_eval 同口径）
        score = 0.0 if outcome["status"] == "FAIL" else 1.0
        return {
            "evaluated": True,
            "score": score,
            **outcome,
        }


register_evaluator("intent", IntentEvaluator)
