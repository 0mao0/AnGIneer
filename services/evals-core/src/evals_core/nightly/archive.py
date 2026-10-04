"""nightly 结论落盘（"发布"仅指写数据文件，与代码 push/系统发版无关）。

<nightly_root>/<YYYY-MM-DD>/{nightly.json, report.md}：夜间维护页的唯一数据源。
结论必须快照化而不是从 evals.sqlite 现算——日常测试页可删 run、门禁 bootstrap 现算慢、
崩溃/超时日本就没有可算的 run，历史（保留 90 天、每天一条不断档）要经得住这些。
"""
import json
import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from . import paths

logger = logging.getLogger(__name__)


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

# 夜间归档保留天数（含当天）。口径与 run 明细三级保留（storage/retention.py）的 90 天
# 上限对齐：页面列表能看到的 = 归档目录，09-12 曾为省磁盘收紧到 3，但每晚归档仅
# ~150KB，90 天 ≈ 15MB，省不出差别，反而把夜间测试页裁成只剩 3 条（2026-09-16 实踩
# 被问「不是改成 90 条了吗」——当时改的是 sqlite 明细窗口，未动这里）。
KEEP_DAYS_DEFAULT = 90
REGRESSION_ITEMS_MAX = 50
FIXED_ITEMS_MAX = 20
_QUESTION_MAX = 300
_DATE_FMT = "%Y-%m-%d"
# 同日已出 green/red 结论时，error 档改落这个 sidecar 文件（来由与保护逻辑见 publish_day，仅旧版单档布局用）
ERROR_SIDECAR = "nightly-error.json"
CONCLUSION_STATES = ("green", "red")
# 每 run 一挡的子目录名：<date>/runs/<slot>/{nightly.json,report.md,...}（2026-09-27 起，同日多跑不互踩）
RUNS_SUBDIR = "runs"


def verdict(state: str, delta, regress_count: int) -> str:
    """≤20 字一句话评价（表格「评价」列）：pp 取整，精确小数留给「基线」列。
    措辞面向普通读者：不写"回归/门禁"等内部术语。

    delta 是配对**净差**，净提升不等于零题转错（2026-09-29 实踩：净 +1.83pp 同时 50 题由对
    转错，卡片仍写"没有题目变差"）⇒「没有…变差」只在 regress_count 为 0 时说，否则报题数。"""
    if state == "error":
        return "评测中断，未出结果"
    if state == "red":
        return f"回退 {regress_count} 题，需排查" if regress_count else "整体变差，需排查"
    if delta is None:
        return "无基线可比，未见变差"
    pp = round(delta * 100)
    if pp >= 1:
        return f"提升 {pp}pp，另有 {regress_count} 题转错" if regress_count else f"提升 {pp}pp，没有题目变差"
    if pp <= -1:
        return f"回落 {abs(pp)}pp，正常波动"
    return f"与基线持平，另有 {regress_count} 题转错" if regress_count else "与基线持平，没有变差"


def load_question_texts(dataset_file: Path) -> dict:
    """题集导出格式 {"items":[...]}（evals 导入件）与 manifest {"questions":[...]} 都兼容。

    仅作历史磁盘副本的只读兼容：2026-09-28 起导入不再落盘，新档一律走 question_texts_from_db。"""
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


def question_texts_from_db(dataset_id: str) -> dict:
    """题干来源（题集只存数据库后的主路）：从 eval_question 读，展示截断口径与 load_question_texts 一致。"""
    from evals_core.storage import result_store  # 延迟导入：archive 模块级不依赖存储层
    try:
        rows = result_store.list_questions(dataset_id)
    except Exception:
        logger.warning("nightly 题干读库失败 dataset_id=%s", dataset_id, exc_info=True)
        return {}
    return {
        str(r["question_id"]): str(r.get("question") or "")[:_QUESTION_MAX]
        for r in rows if r.get("question_id") and r.get("question")
    }


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
                subject: str = "", started_at: str = "", judge_missing: Optional[dict] = None) -> dict:
    """门禁结论 + run 汇总 → 单日 nightly.json 条目（键与站点接口/前端协议一致）。

    subject=维护内容（如"Open RAG Benchmark 子集 v2（487 题）"）：写入时固化，
    日后维护内容扩展（不只评测集）时老条目不受改名影响。
    started_at=run 开跑时间（evals 库原值，UTC naive），表「时间」列语义=开跑时刻、
    「时长」=generated_at−started_at；历史条目缺该字段前端显示“—”。
    judge_missing=阈值内放行的判分缺失题 {异常类型: [question_id]}：不参与门禁，
    只落进条目供页面与回溯查看——放行必须可查，否则与静默无异。"""
    matrix = {k: (gate.get("matrix") or {}).get(k) for k in ("pp", "pf", "fp", "ff")}
    summary = summary_scores or {}
    regressions = gate.get("regressions") or {}
    reg_ids = [qid for qid, _ in sorted(regressions.items(), key=lambda kv: (kv[1], kv[0]))]
    entry = {
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
    if judge_missing:
        entry["judge_missing"] = {k: sorted(v) for k, v in judge_missing.items() if v}
    return entry


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

    keep_days 含当天（keep_days=90 → 今天往前 89 天）；
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
                keep_days: int = KEEP_DAYS_DEFAULT, slot: str = "") -> Path:
    """写一档结论并清理过期。

    slot 非空（现行管线）：落 <date>/runs/<slot>/，同日每跑一挡、天然不互相覆盖，
    条目带上 "slot" 字段供页面定位详情/删除。
    slot 为空（旧版「当日单档」兼容口）：同日重跑覆盖主位，唯一例外——error 档不得
    覆盖同日已出的 green/red 结论（2026-09-26 实踩：00:32 的完整结论被 03:17 定时的
    error 原地盖掉）；error 改落 sidecar，结论与失败详情都在。"""
    root = Path(root) if root else paths.nightly_root()
    day_dir = root / str(entry["date"])
    if slot:
        target_dir = day_dir / RUNS_SUBDIR / str(slot)
        target_dir.mkdir(parents=True, exist_ok=True)
        entry = {**entry, "slot": str(slot)}
        (target_dir / "nightly.json").write_text(
            json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
        if report_md:
            (target_dir / "report.md").write_text(report_md, encoding="utf-8")
        prune_old(root, keep_days, str(entry["date"]))
        return target_dir
    day_dir.mkdir(parents=True, exist_ok=True)
    target = day_dir / "nightly.json"
    if entry.get("state") == "error" and _has_conclusion(target):
        logger.info("当天已有 green/red 结论，error 档改落 %s（不覆盖结论）", ERROR_SIDECAR)
        target = day_dir / ERROR_SIDECAR
    target.write_text(json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
    if report_md:
        if target.name == ERROR_SIDECAR:
            logger.warning("error 档带报告但当天结论的 report.md 已在，保留结论报告不覆盖")
        else:
            (day_dir / "report.md").write_text(report_md, encoding="utf-8")
    prune_old(root, keep_days, str(entry["date"]))
    return day_dir


def read_entry(entry_dir: Path, date: str, slot: str = "") -> dict:
    """读一挡（slot 目录或旧版日目录）的 nightly.json 为列表/详情条目。
    缺失/损坏降级为 corrupt，不炸整个列表；corrupt_reason 区分「文件缺失」（中断档，
    resolve_interrupted 可重判）与「真不可读」（维持 corrupt 语义不稀释）；
    同日 error sidecar 要点随条目透出（旧版单档规矩）。"""
    entry_dir = Path(entry_dir)
    try:
        data = json.loads((entry_dir / "nightly.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("nightly.json 不是对象")
        data.setdefault("slot", slot)
    except FileNotFoundError:
        return {"date": date, "slot": slot, "state": "corrupt", "corrupt_reason": "missing"}
    except (OSError, ValueError):
        return {"date": date, "slot": slot, "state": "corrupt", "corrupt_reason": "unreadable"}
    data["date"] = date
    sidecar = read_day_error(entry_dir)
    if sidecar:
        data["same_day_error"] = {k: sidecar.get(k) for k in
                                  ("generated_at", "started_at", "run_id", "verdict", "note", "progress")}
    return data


def _bjt_day(iso: str) -> str:
    """run 时间戳（UTC naive）的北京日期 YYYY-MM-DD；解析失败返回空串。"""
    return _to_bjt(str(iso or ""))[:10]


def _covers_day(run: dict, day: str) -> bool:
    """run 的活跃区间 [started_at, completed_at]（北京日期）是否覆盖 day。"""
    start = _bjt_day(run.get("started_at"))
    if not start or not day:
        return False
    end = _bjt_day(run.get("completed_at")) or start
    return start <= day <= end


def _fill_interrupted(entry: dict, run: dict) -> None:
    """把 corrupt 占位条目改写成 interrupted：时间/进度/指路文案全部取 DB 口径。"""
    summary = run.get("summary_scores") or {}
    total = int(run.get("total_questions") or summary.get("total") or 0)
    completed = int(run.get("completed_questions") or 0)
    correct = int(summary.get("correct") or 0)
    entry.update({
        "state": "interrupted",
        "run_id": run.get("run_id") or "",
        "dataset_id": run.get("dataset_id") or "",
        "started_at": _to_bjt(str(run.get("started_at") or "")),
        # 盖章时刻=中断收口时刻，作 generated_at 供「时长」列
        "generated_at": _to_bjt(str(run.get("completed_at") or "")),
        # 部分进度只进展示（同 error 档 progress 语义），不参与门禁；sweep 汇总的
        # overall_score 恒 0.0，绝不回填成「平均分」列
        "progress": {
            "completed": completed,
            "total": total,
            "correct": correct,
            "score": round(correct / completed, 4) if completed else None,
        },
        "verdict": f"评测被部署/重启中断于 {completed}/{total or '?'}，可到「日常测试」点「继续评测」断点续跑",
    })


def resolve_interrupted(entries: list, dataset_id: str = "") -> list:
    """corrupt 挡重判（req-nightly-interrupt-resume §2-B2）：有 B 层产物、无结论文件的
    挡位若存在「被部署/重启砸掉」的 run（cancelled + 启动清扫中断章）且活跃区间覆盖
    挡日期，改判 interrupted 并回填 DB 口径的时间与已完成数。

    slot↔run 配对：slot 名（HHMM-6hex）不含 run_id，且素材检查先于评测建档、续跑保留
    原 started_at（result_store.reset_run_for_resume），都不能按分钟对时——改为同日内
    corrupt 挡按挡名序、候选 run 按 started_at 序一一配对（同日多中断是稀有形态，定序
    配对保证确定性）。无候选维持 corrupt（真损坏语义不稀释）；无章 cancelled（人为停止）
    不算中断——「中断」与断点续跑探测同判据，页面上中断=可续跑。"""
    targets = [e for e in entries
               if e.get("state") == "corrupt" and e.get("corrupt_reason") == "missing"]
    if not targets:
        return entries
    from evals_core.storage import result_store  # 延迟导入：archive 模块级不依赖存储层
    try:
        runs = result_store.list_runs(dataset_id or None)
    except Exception:  # noqa: BLE001 库不可用不拖垮列表（维持 corrupt）
        logger.warning("中断档重判读库失败", exc_info=True)
        return entries
    candidates = sorted(
        (r for r in runs
         if r.get("status") == "cancelled"
         and (r.get("summary_scores") or {}).get("interrupted_by_startup_sweep")),
        key=lambda r: str(r.get("started_at") or ""),
    )
    if not candidates:
        return entries
    used = set()
    for entry in sorted(targets, key=lambda e: (str(e.get("date") or ""), str(e.get("slot") or ""))):
        day = str(entry.get("date") or "")
        hit = next((r for r in candidates
                    if str(r.get("run_id") or "") not in used and _covers_day(r, day)), None)
        if hit is None:
            continue
        used.add(str(hit.get("run_id") or ""))
        _fill_interrupted(entry, hit)
    return entries


def list_entries(day_dir: Path, date: str, dataset_id: str = "") -> list:
    """一日内全部结论挡（新版每 run 一挡 + 旧版当日单档），按时间新→旧。

    排序键：started_at 优先（表「时间」列语义=开跑时刻），退 generated_at，再退挡名；
    corrupt 挡排在该日最后（无时间可比）。dataset_id 非空时 corrupt 挡先做中断重判
    （resolve_interrupted），重判命中的档带时间，参与正常排序。"""
    day_dir = Path(day_dir)
    entries = []
    if (day_dir / "nightly.json").exists():
        entries.append(read_entry(day_dir, date))
    runs = day_dir / RUNS_SUBDIR
    if runs.is_dir():
        for slot_dir in runs.iterdir():
            if slot_dir.is_dir():
                entries.append(read_entry(slot_dir, date, slot=slot_dir.name))
    if dataset_id:
        resolve_interrupted(entries, dataset_id)

    def _key(entry):
        if entry.get("state") == "corrupt":
            return " "
        return str(entry.get("started_at") or entry.get("generated_at") or entry.get("slot") or "")

    entries.sort(key=_key, reverse=True)
    return entries


def _has_conclusion(target: Path) -> bool:
    """该文件当前是否是一份真结论（green/red）。读不出/损坏一律按「没有」→ error 照旧覆盖写主位。"""
    try:
        return json.loads(target.read_text(encoding="utf-8")).get("state") in CONCLUSION_STATES
    except (AttributeError, OSError, ValueError):
        return False


def read_day_error(day_dir: Path) -> Optional[dict]:
    """读当天的 error sidecar（同日既出了结论又跑挂了时给页面留个可见口）。无/坏返回 None。"""
    try:
        data = json.loads((Path(day_dir) / ERROR_SIDECAR).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None
