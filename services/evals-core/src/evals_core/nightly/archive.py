"""nightly 结论落盘（"发布"仅指写数据文件，与代码 push/系统发版无关）。

<nightly_root>/<YYYY-MM-DD>/{nightly.json, report.md}：夜间维护页的唯一数据源。
结论必须快照化而不是从 evals.sqlite 现算——日常测试页可删 run、门禁 bootstrap 现算慢、
崩溃/超时日本就没有可算的 run，历史（保留 3 天、每天一条不断档）要经得住这些。
"""
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import paths


def _to_bjt(iso: str) -> str:
    """evals 库存的 started_at 是 UTC naive，统一转北京 +08 带偏移（与 generated_at 同口径），
    前端 new Date 可直接解析；空值/解析失败返回空串（前端显示“—”）。"""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(paths.BJT).isoformat(timespec="seconds")
    except ValueError:
        return ""

# 夜间归档保留天数（含当天）：3 = 今天/昨天/前天三条。2026-09-12 起由 30 天收紧，
# 磁盘与页面只留近三天（publish 时按目录名裁剪，见 prune_old）。
KEEP_DAYS_DEFAULT = 3
REGRESSION_ITEMS_MAX = 50
FIXED_ITEMS_MAX = 20
_QUESTION_MAX = 300
_DATE_FMT = "%Y-%m-%d"


def verdict(state: str, delta, regress_count: int) -> str:
    """≤20 字一句话评价（表格「评价」列）：pp 取整，精确小数留给「基线」列。
    措辞面向普通读者：不写"回归/门禁"等内部术语。"""
    if state == "error":
        return "评测中断，未出结果"
    if state == "red":
        return f"回退 {regress_count} 题，需排查" if regress_count else "整体变差，需排查"
    if delta is None:
        return "无基线可比，未见变差"
    pp = round(delta * 100)
    if pp >= 1:
        return f"提升 {pp}pp，没有题目变差"
    if pp <= -1:
        return f"回落 {abs(pp)}pp，正常波动"
    return "与基线持平，没有变差"


def load_question_texts(dataset_file: Path) -> dict:
    """题集导出格式 {"items":[...]}（evals 导入件）与 manifest {"questions":[...]} 都兼容。"""
    try:
        data = json.loads(Path(dataset_file).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    rows = (data.get("items") or data.get("questions")) if isinstance(data, dict) else None
    for q in rows or []:
        if not isinstance(q, dict):
            continue
        qid, text = q.get("question_id") or q.get("uuid"), str(q.get("question") or q.get("query") or "")
        if qid and text:
            out[str(qid)] = text[:_QUESTION_MAX]
    return out


def _question_items(qids, buckets: dict, question_texts: dict, limit: int, evidence_map: dict = None) -> list:
    items = []
    for qid in list(qids)[:limit]:
        bucket = str(buckets.get(qid) or "")
        item = {
            "qid": qid,
            "question": question_texts.get(str(qid), ""),
            "bucket": bucket.split("(", 1)[0],  # 机读码，前端映射大白话；原始串留 tooltip
            "bucket_detail": bucket,
        }
        ev = (evidence_map or {}).get(str(qid))
        if ev:
            item["evidence"] = ev  # 逐题前后对比证据（展开查看"问题具体在哪"）
        items.append(item)
    return items


def build_entry(gate: dict, summary_scores: dict, question_texts: dict,
                dataset_id: str, date: str, run_id: str = "", state: str = "green",
                subject: str = "", started_at: str = "") -> dict:
    """门禁结论 + run 汇总 → 单日 nightly.json 条目（键与站点接口/前端协议一致）。

    subject=维护内容（如"Open RAG Benchmark 子集 v2（487 题）"）：写入时固化，
    日后维护内容扩展（不只评测集）时老条目不受改名影响。
    started_at=run 开跑时间（evals 库原值，UTC naive），表「时间」列语义=开跑时刻、
    「时长」=generated_at−started_at；历史条目缺该字段前端显示“—”。"""
    matrix = {k: (gate.get("matrix") or {}).get(k) for k in ("pp", "pf", "fp", "ff")}
    summary = summary_scores or {}
    regressions = gate.get("regressions") or {}
    reg_ids = [qid for qid, _ in sorted(regressions.items(), key=lambda kv: (kv[1], kv[0]))]
    return {
        "date": date,
        "state": state,
        "generated_at": datetime.now(paths.BJT).isoformat(),
        "started_at": _to_bjt(started_at),
        "run_id": run_id or gate.get("new") or "",
        "dataset_id": dataset_id,
        "subject": subject or dataset_id,
        "overall_score": summary.get("overall_score"),
        "correct": summary.get("correct"),
        "total": summary.get("total"),
        "errored": summary.get("errored"),
        "judge_failed_count": summary.get("judge_failed_count"),
        # 判分引擎留痕（legacy/deepeval）：跨 run 对比时识别判分口径切换
        "eval_engine": summary.get("eval_engine"),
        "delta": gate.get("delta"),
        "delta_ci95": gate.get("delta_ci95"),
        "base_label": gate.get("base_label"),
        "matrix": matrix,
        "gate_reasons": gate.get("gate_reasons") or [],
        "regressions": regressions,
        "verdict": verdict(state, gate.get("delta"), len(regressions)),
        "regression_items": _question_items(
            reg_ids, regressions, question_texts, REGRESSION_ITEMS_MAX, gate.get("regression_details") or {}),
        "fixed_items": _question_items(gate.get("fixed") or [], {}, question_texts, FIXED_ITEMS_MAX),
    }


def build_error_entry(dataset_id: str, date: str, note: str, subject: str = "",
                      started_at: str = "", progress: Optional[dict] = None) -> dict:
    """error 档条目：失败也要每天一条、绝不断档。

    progress = {completed, total, correct, score}：run 已建档但没跑完时的部分进度。
    只进条目供展示（页面「题量/平均分」列与展开明细），**不参与门禁**——门禁只在 run
    正常完成时计算，部分样本算出的分不能当结论。
    2026-09-12 教训：超时只写一句"无结论"，把整晚 437 题的结果一起扔掉了。"""
    entry = {
        "date": date,
        "state": "error",
        "generated_at": datetime.now(paths.BJT).isoformat(),
        "started_at": _to_bjt(started_at),
        "dataset_id": dataset_id,
        "subject": subject or dataset_id,
        "verdict": verdict("error", None, 0),
        "note": note or "评测环节未完成（上游步骤失败）",
    }
    if progress and progress.get("completed"):
        entry["progress"] = progress
        entry["verdict"] = f"中断于 {progress['completed']}/{progress.get('total') or '?'}，未出结论"
    return entry


def prune_old(target_root: Path, keep_days: int, today: str) -> list:
    """按日期名清理旧目录：保留「今天 + 前 keep_days-1 天」。

    keep_days 含当天（keep_days=3 → 今天/昨天/前天），与 settings 里"近三天"口径一致；
    目录名不合法日期的不动，人工排查留证。"""
    removed = []
    try:
        floor = (datetime.strptime(today, _DATE_FMT)
                 - timedelta(days=max(keep_days - 1, 0))).strftime(_DATE_FMT)
    except ValueError:
        return removed
    for day in sorted(target_root.iterdir()):
        if not day.is_dir():
            continue
        try:
            datetime.strptime(day.name, _DATE_FMT)
        except ValueError:
            continue
        if day.name < floor:
            shutil.rmtree(day, ignore_errors=True)
            removed.append(day.name)
    return removed


def publish_day(entry: dict, report_md: Optional[str], root: Optional[Path] = None,
                keep_days: int = KEEP_DAYS_DEFAULT) -> Path:
    """写单日结论目录并清理过期（幂等：同日重跑覆盖）。"""
    root = Path(root) if root else paths.nightly_root()
    day_dir = root / str(entry["date"])
    day_dir.mkdir(parents=True, exist_ok=True)
    (day_dir / "nightly.json").write_text(
        json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    if report_md:
        (day_dir / "report.md").write_text(report_md, encoding="utf-8")
    prune_old(root, keep_days, str(entry["date"]))
    return day_dir
