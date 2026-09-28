"""探针评测器：题目带 probe 断言块时只做检索层断言，不跑生成、不跑判官。

真相源说明（2026-09-29）：断言逻辑原只在 scripts/clause_probe.py，UI 运行链路
（本文件）拿不到断言——题集入库时 probe 块又被 bundle schema 丢弃。现断言块随
EvalQuestionItem.probe / eval_question.probe_gold 入库，断言逻辑收口到本文件，
脚本改为复用这里。

解耦口径：evals-core 不依赖 docs-core。检索函数由宿主（aichat-api）在启动时
经 set_retriever() 注入；未注入时 probe 题直接报错，不静默跳过。

xfail 语义（与脚本一致）：checks 挂 = 已知缺口仍在（XFAIL-OK，记 correct）；
全过 = 缺口已修（XPASS，记 correct 并提示摘除 xfail 标记）。
"""
from typing import Any, Callable, Dict, List, Optional

from evals_core.runner.base import BaseEvaluator, register_evaluator

DEFAULT_TOP_K = 20

_retriever: Optional[Callable[..., Dict[str, Any]]] = None


def set_retriever(fn: Optional[Callable[..., Dict[str, Any]]]) -> None:
    """注入原始检索函数（签名兼容 docs_core retrieve_knowledge）。"""
    global _retriever
    _retriever = fn


def is_clause_item(e: Dict[str, Any]) -> bool:
    """判定一条检索结果是否条款直达项（clause_resolver 契约，89735bb）。"""
    pol = str(e.get("retrieval_policy") or "")
    md = e.get("metadata") or {}
    if "clause" in pol or str(md.get("source_kind") or "") == "clause_direct":
        return True
    fs = md.get("fusion_sources") or []
    if isinstance(fs, str):
        fs = fs.split(",")
    return "clause" in [str(x).strip() for x in fs]


def run_probe_item(item: Dict[str, Any], items: List[Dict[str, Any]]) -> Dict[str, Any]:
    """对单题的检索结果跑全部断言，返回 checks/failed/status。

    item 需带 probe 块；items 为原始检索结果列表（保序）。
    """
    probe = item.get("probe") or {}
    expect_clause = bool(probe.get("expect_clause_direct"))
    xfail = bool(probe.get("xfail"))
    clause_items = [e for e in items if is_clause_item(e)]
    checks: Dict[str, str] = {}

    # ① 路由层：直达是否按预期出现
    checks["clause_direct"] = "ok" if bool(clause_items) == expect_clause else (
        f"实际={'有' if clause_items else '无'} 期望={'有' if expect_clause else '无'}")

    if clause_items:
        # P1-1 限域：所有直达项必须出自点名文档
        restricted = probe.get("restricted_doc")
        if restricted:
            bad = sorted({str(e.get("doc_id")) for e in clause_items} - {restricted})
            checks["restricted_doc"] = "ok" if not bad else f"混入 {bad}"
        # P0-2 主题加权：条款组首位必须出自期望文档
        top_docs = probe.get("top_clause_docs")
        if top_docs:
            first_doc = str(clause_items[0].get("doc_id"))
            checks["top_clause_doc"] = "ok" if first_doc in top_docs else f"首位 {first_doc} ∉ {top_docs}"
        # ② 检索层：金标条款块整体位次
        gold_num = probe.get("gold_num")
        gold_docs = probe.get("gold_doc_for_num") or []
        if gold_num and gold_docs:
            rank = next(
                (i for i, e in enumerate(items, 1)
                 if is_clause_item(e) and str(e.get("doc_id")) in gold_docs
                 and gold_num in str(e.get("text") or "")),
                None,
            )
            limit = int(probe.get("precise_rank_max") or 0)
            if rank is None:
                checks["precise_rank"] = f"金标条款块（{gold_num}）未进 top-{len(items)}"
            elif limit and rank > limit:
                checks["precise_rank"] = f"位次 {rank} > 上限 {limit}"
            else:
                checks["precise_rank"] = f"ok(rank={rank})"

    failed = [k for k, v in checks.items()
              if v != "ok" and not str(v).startswith("ok(")]
    if xfail:
        status = "XFAIL-OK" if failed else "XPASS(请摘xfail)"
    else:
        status = "FAIL" if failed else "PASS"
    return {
        "checks": checks,
        "failed": failed,
        "status": status,
        "xfail": xfail,
        "n_clause": len(clause_items),
        "n_items": len(items),
    }


class ProbeEvaluator(BaseEvaluator):
    """探针题评测器：run_prediction 只跑检索，evaluate 跑断言。"""

    def run_prediction(self, question: Dict[str, Any], *, stage_callback: Optional[Callable] = None) -> Dict[str, Any]:
        if _retriever is None:
            return {"error": "probe 评测器未注入检索函数（宿主启动需调 probe_eval.set_retriever）"}
        result = _retriever(
            query=str(question.get("question") or ""),
            library_id=str(question.get("library_id") or "default"),
            doc_ids=[],
            top_k=DEFAULT_TOP_K,
            task_type="definition",
            mode="text",
        )
        prediction = {
            "items": (result or {}).get("items") or [],
            "probe_mode": "retrieve_only",
        }
        if stage_callback:
            stage_callback(prediction)
        return prediction

    def evaluate(self, question: Dict[str, Any], gold: Dict[str, Any], prediction: Dict[str, Any]) -> Dict[str, Any]:
        probe = gold or question.get("probe_gold") or {}
        outcome = run_probe_item({"probe": probe}, prediction.get("items") or [])
        # quality 映射走 _decide_quality 的 score 阈值：FAIL 给通过率（<0.8 → wrong），
        # PASS/XFAIL-OK/XPASS 给 1.0（xfail 挂账题按预期失败记过，与脚本 exit 0 同口径）
        total = len(outcome["checks"]) or 1
        n_ok = total - len(outcome["failed"])
        score = 1.0 if outcome["status"] != "FAIL" else round(n_ok / total, 4)
        return {
            "evaluated": True,
            "score": score,
            **outcome,
        }


register_evaluator("probe", ProbeEvaluator)
