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
- 时间戳：2026-10-07 起 result_store 写带偏移的 UTC 串（...+00:00），历史行为裸串
  按 UTC 读；日期分层 astimezone(+08) 折北京日界——UTC 晚间完成的 run 属北京"次日"，
  不折会把窗口内 run 裁早（test_bjt_boundary 钉住）；
- 删除必须显式删明细（CASCADE 从未开启，2026-09-12 实踩 1.1G 孤儿明细）；
- 不自动 VACUUM：夜间对 1.4G 库做 VACUUM 会阻塞写方，且 sqlite 会复用 freelist 页，
  策略稳定运行后文件自然收敛（一次性手动 VACUUM 见发版说明）。
"""
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from . import result_store

# 过程快照字段：仅排查用，判分/报告/门禁不读（字段清单按 2026-09-15 实测定型）
SNAPSHOT_KEYS = ("retrieval_debug", "retrieved_items", "evidences", "route_debug", "flow_debug", "trace_meta")

KEEP_FULL_DAYS_DEFAULT = 3
DELETE_AFTER_DAYS_DEFAULT = 90

# 裁剪/删除的分批提交行数（2026-10-02 实踩：5 个过期 run 数千行 UPDATE 攒到 enforce
# 末尾才提交，一笔写事务独占 WAL 写锁 ~7.5 分钟，撞锁的补判线程 complete_run 抛
# database is locked 后无重试直接死亡，run 永卡 running、nightly 干等 7 小时判超时）。
# 分批边界取 200：一批 ≈数十毫秒，其他写者按 busy_timeout 排队即过。
COMMIT_BATCH_ROWS = 200


def baseline_run_id() -> str:
    """基线指针指向的 run_id 集合，逗号拼接（无指针/读失败返回空串——只影响保护名单，不抛错）。

    2026-10-08 起观察集有专属指针 `baseline_run.<dataset_id>.json`，全部纳入保护：
    否则 90 天后 FB-150 基线 run 被 GC，专属基线快照对不上 run 明细。
    返回保持 str（调用方按单串比较，多 run 时该串不匹配任何单个 run_id 属已知保守行为，
    基线 run 通常远低于 90 天窗口）。"""
    import glob
    base = os.path.join(os.path.dirname(result_store._DB_PATH), "baseline")
    ids = []
    for pattern in ("baseline_run.json", "baseline_run.*.json"):
        for path in glob.glob(os.path.join(base, pattern)):
            try:
                with open(path, encoding="utf-8") as fh:
                    rid = str(json.load(fh).get("run_id") or "")
            except (OSError, ValueError):
                continue
            if rid and rid not in ids:
                ids.append(rid)
    return ",".join(ids)


def _bjt_date(ts: Any) -> Optional[str]:
    """时间戳 → 北京时间日期串；解析失败返回 None（该行跳过不动）。
    2026-10-07 起新行带偏移（+00:00），历史裸串按 UTC 读：统一 astimezone(+08)。
    不再无条件 +8h——对带偏移串再加 8 小时会多跳一天日界。"""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(str(ts))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
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
    """裁一个 run 的过程快照，返回实际改写的行数。

    每改 COMMIT_BATCH_ROWS 行提交一次：写锁分段释放，评测收尾/补判等并发写者
    按 busy_timeout 排队即过，不会被一笔跨分钟的大事务挡死（模块头注释）。
    逐行 UPDATE 按 rowid 定位、天然幂等，中途崩溃只会留下"半裁剪"状态，
    下轮 enforce 继续裁剩余行，无需回滚。"""
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
        if changed % COMMIT_BATCH_ROWS == 0:
            conn.commit()
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
            conn.commit()  # run 间也提交一次，收尾批（不足 COMMIT_BATCH_ROWS 的行）单独落盘
            compacted += 1
    if deleted_ids:
        result_store.delete_runs(conn, deleted_ids)
    conn.commit()
    return {"full": full, "compacted_runs": compacted, "deleted_runs": deleted, "deleted_ids": deleted_ids}


def enforce_after_run(**kwargs) -> Dict[str, Any]:
    """run 收尾接线点：以当前北京时间与基线指针执行策略。异常由调用方兜底。"""
    today = (datetime.utcnow() + timedelta(hours=8)).strftime("%Y-%m-%d")
    conn = result_store._get_conn()
    stats = enforce(conn, today, baseline_run=baseline_run_id(), **kwargs)
    if stats["compacted_runs"] or stats["deleted_runs"]:
        # 大批量改写后主动收缩 WAL（实测清理一轮可滞留 GB 级 WAL，逼近部署机磁盘红线）。
        # TRUNCATE 需无并发读者，抢不到锁 sqlite 直接返回 busy 不阻塞——best-effort，
        # 平时无害；日常收缩仍靠 sqlite 自动 checkpoint。
        try:
            conn.execute("pragma wal_checkpoint(TRUNCATE)")
        except Exception:  # noqa: BLE001
            pass
    return stats
