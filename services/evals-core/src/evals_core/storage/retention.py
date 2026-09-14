"""run 明细三级保留策略（2026-09-15 磁盘策略）。

背景：一次 526 题全量 run 逐题明细 ≈230 MiB，其中 ~99% 是过程快照
（retrieval_debug/retrieved_items/evidences 等检索调试现场），判分/报告/基线只用
scores + answer + citations + 路由结论（实测 ≈2 MiB/run，见 test_retention）。

三级策略（按 run 完成的北京时间日界分层）：
- 距今 < keep_full_days（含当天）：全量保留，UI 可回看当时召回原文；
- keep_full_days ~ delete_after_days：裁掉过程快照字段，保留结论字段——rescore 判分
  只需要 answer vs 金标（扩展维度 EVAL_DEEPVAL_EXTRA=0 才不依赖证据原文，开扩展维度
  等于放弃本策略的存储收益）；
- ≥ delete_after_days：整 run 删除；基线指针 run（gate 读的独立快照文件虽不依赖
  库内行，但留库供 UI 溯源）与 running run 不删。

设计约束：
- 时间戳按 naive UTC 存储（result_store 现状），日期分层 +8h 折北京日界——UTC 晚间
  完成的 run 属北京"次日"，不折会把窗口内 run 裁早（test_bjt_boundary 钉住）；
- 删除必须显式删明细（CASCADE 从未开启，2026-09-12 实踩 1.1G 孤儿明细）；
- 不自动 VACUUM：夜间对 1.4G 库做 VACUUM 会阻塞写方，且 sqlite 会复用 freelist 页，
  策略稳定运行后文件自然收敛（一次性手动 VACUUM 见发版说明）。
"""
import json
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from . import result_store

# 过程快照字段：仅排查用，判分/报告/门禁不读（字段清单按 2026-09-15 实测定型）
SNAPSHOT_KEYS = ("retrieval_debug", "retrieved_items", "evidences", "route_debug", "flow_debug", "trace_meta")

KEEP_FULL_DAYS_DEFAULT = 3
DELETE_AFTER_DAYS_DEFAULT = 90


def baseline_run_id() -> str:
    """基线指针指向的 run_id（无指针/读失败返回空串——只影响保护名单，不抛错）。"""
    pointer = os.path.join(os.path.dirname(result_store._DB_PATH), "baseline", "baseline_run.json")
    try:
        with open(pointer, encoding="utf-8") as fh:
            return str(json.load(fh).get("run_id") or "")
    except (OSError, ValueError):
        return ""


def _bjt_date(ts: Any) -> Optional[str]:
    """naive UTC 时间戳 → 北京时间日期串；解析失败返回 None（该行跳过不动）。"""
    if not ts:
        return None
    try:
        return (datetime.fromisoformat(str(ts)) + timedelta(hours=8)).strftime("%Y-%m-%d")
    except ValueError:
        return None


def _strip_snapshot(raw: Optional[str]) -> Optional[str]:
    """裁一行 JSON 里的过程快照字段；无变化/解析失败返回 None（=不写回，幂等且保留脏数据）。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    if not (obj.keys() & set(SNAPSHOT_KEYS)):
        return None
    slimmed = {k: v for k, v in obj.items() if k not in SNAPSHOT_KEYS}
    return json.dumps(slimmed, ensure_ascii=False)


def _strip_multi(raw: Optional[str]) -> Optional[str]:
    """all_predictions：每个评测器的 prediction 各自裁。"""
    if not raw:
        return None
    try:
        obj = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(obj, dict):
        return None
    hit = False
    for ev, pred in list(obj.items()):
        if isinstance(pred, str):
            inner = _strip_snapshot(pred)
            if inner is not None:
                obj[ev] = inner
                hit = True
        elif isinstance(pred, dict) and pred.keys() & set(SNAPSHOT_KEYS):
            obj[ev] = {k: v for k, v in pred.items() if k not in SNAPSHOT_KEYS}
            hit = True
    return json.dumps(obj, ensure_ascii=False) if hit else None


def _compact_run(conn, run_id: str) -> int:
    """裁一个 run 的过程快照，返回实际改写的行数。"""
    rows = conn.execute(
        "select rowid AS rid, prediction, all_predictions from eval_run_detail where run_id=?", (run_id,)).fetchall()
    changed = 0
    for row in rows:
        new_pred = _strip_snapshot(row["prediction"])
        new_multi = _strip_multi(row["all_predictions"])
        if new_pred is None and new_multi is None:
            continue
        sets, vals = [], []
        if new_pred is not None:
            sets.append("prediction = ?")
            vals.append(new_pred)
        if new_multi is not None:
            sets.append("all_predictions = ?")
            vals.append(new_multi)
        vals.append(row["rid"])
        conn.execute(f"update eval_run_detail set {', '.join(sets)} where rowid = ?", vals)
        changed += 1
    return changed


def enforce(conn, today_bjt: str, *, baseline_run: str = "",
            keep_full_days: int = KEEP_FULL_DAYS_DEFAULT,
            delete_after_days: int = DELETE_AFTER_DAYS_DEFAULT) -> Dict[str, Any]:
    """按三级策略清理 run。today_bjt=YYYY-MM-DD（北京时间）。返回统计 dict。"""
    try:
        today = datetime.strptime(today_bjt, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"today_bjt 需为 YYYY-MM-DD，got {today_bjt!r}")
    full_floor = (today - timedelta(days=max(keep_full_days - 1, 0))).strftime("%Y-%m-%d")
    delete_before = (today - timedelta(days=delete_after_days)).strftime("%Y-%m-%d")

    compacted = deleted = full = 0
    deleted_ids = []
    for run in conn.execute("select run_id, status, started_at, completed_at from eval_run").fetchall():
        run_id, status = run["run_id"], run["status"]
        if status == "running":
            continue
        date = _bjt_date(run["completed_at"] or run["started_at"])
        if date is None:
            continue
        if date >= full_floor:
            full += 1
            continue
        if date < delete_before and run_id != baseline_run:
            deleted_ids.append(run_id)
            deleted += 1
            continue
        if _compact_run(conn, run_id):
            compacted += 1
    if deleted_ids:
        result_store.delete_runs(conn, deleted_ids)
    conn.commit()
    return {"full": full, "compacted_runs": compacted, "deleted_runs": deleted, "deleted_ids": deleted_ids}


def enforce_after_run(**kwargs) -> Dict[str, Any]:
    """run 收尾接线点：以当前北京时间与基线指针执行策略。异常由调用方兜底。"""
    today = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
    return enforce(result_store._get_conn(), today, baseline_run=baseline_run_id(), **kwargs)
