"""evals.sqlite 磁盘体检与回收（运维脚本，与主流程解耦）。

背景（2026-09-12 生产实踩）
--------------------------
eval_run_detail.run_id 在 schema 里声明了 ON DELETE CASCADE，但那只是"外键级联"，
只在 PRAGMA foreign_keys=ON 时生效——SQLite 默认关闭，本项目连接从未开过。
后果：删 eval_run 只删了 run 行，逐题明细（实测 ~220MB/轮）永久滞留。
服务器 evals.sqlite 2.15GB 里 1.1GB 是 12 轮"已删除 run"的孤儿明细；
auto_vacuum=0、freelist 仅 25 页 → 空间既不回收也不被复用。

代码侧已改成显式删明细（result_store._delete_run_details / delete_runs），
本脚本负责（a）清理存量孤儿、（b）把腾出来的空间真正还给文件系统。

用法（仓库根目录执行；容器内同构路径 python /app/scripts/evals_db_gc.py）
--------------------------------------------------------------------
  python scripts/evals_db_gc.py                        # 只体检，不动数据
  python scripts/evals_db_gc.py --purge-orphans         # 删孤儿明细（只删父 run 已不存在的行）
  python scripts/evals_db_gc.py --purge-orphans --vacuum   # 再把空间还给文件系统
  python scripts/evals_db_gc.py --older-than-days 3     # 仅列出超过 N 天的整轮 run
  python scripts/evals_db_gc.py --older-than-days 3 --purge-orphans --vacuum

注意：VACUUM 独占写锁（2GB 库约 1~3 分钟），请在无评测运行时执行。
"""
import argparse
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_DB = REPO / "data" / "evals" / "evals.sqlite"
BJT = timezone(timedelta(hours=8))
PAYLOAD = ("(length(coalesce(prediction,'')) + length(coalesce(scores,'')) "
           "+ length(coalesce(all_scores,'')) + length(coalesce(all_predictions,'')) "
           "+ length(coalesce(error,'')))")


def _connect(path: Path) -> sqlite3.Connection:
    # timeout=60：线上库里可能还有服务在写，VACUUM 要独占锁，给足等待窗口
    conn = sqlite3.connect(str(path), timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


def _mb(value) -> float:
    return round(float(value or 0) / 1048576, 1)


def _bytes(conn: sqlite3.Connection) -> int:
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    page_count = conn.execute("PRAGMA page_count").fetchone()[0]
    return page_size * page_count


def _size(value) -> str:
    """人类可读大小：小于 1GB 用 MB（避免 0.00 GB 这种没信息量的输出）。"""
    value = float(value or 0)
    return f"{value / 1048576:.1f} MB" if value < 1073741824 else f"{value / 1073741824:.2f} GB"


def _existing_tables(conn: sqlite3.Connection) -> set:
    return {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def _bjt_date(iso: str):
    """evals 库存的 started_at 是 UTC naive；转北京日期（与 nightly 归档同日历口径）。"""
    try:
        dt = datetime.fromisoformat(str(iso))
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BJT).date()


def report(conn: sqlite3.Connection, db: Path) -> None:
    print("== 体检 ==")
    print(f"库路径 : {db}")
    print(f"库大小 : {_size(_bytes(conn))}（page_count × page_size）")
    print(f"磁盘占用: {_size(db.stat().st_size)}")
    free_pages = conn.execute("PRAGMA freelist_count").fetchone()[0]
    page_size = conn.execute("PRAGMA page_size").fetchone()[0]
    print(f"空闲页 : {free_pages} 页（{_size(free_pages * page_size)}）"
          f" / auto_vacuum={conn.execute('PRAGMA auto_vacuum').fetchone()[0]}"
          f" / journal={conn.execute('PRAGMA journal_mode').fetchone()[0]}")
    tables = _existing_tables(conn)
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("eval_dataset", "eval_question", "eval_run", "eval_run_detail") if t in tables}
    print("行数   : " + ", ".join(f"{k}={v}" for k, v in counts.items()))
    payload = conn.execute(f"SELECT SUM({PAYLOAD}) FROM eval_run_detail").fetchone()[0]
    print(f"明细载荷: {_mb(payload)} MB（prediction+scores+all_scores+all_predictions+error）")

    orphans = conn.execute(
        f"SELECT d.run_id, COUNT(*) AS n, SUM({PAYLOAD}) AS bytes FROM eval_run_detail d "
        "WHERE d.run_id NOT IN (SELECT run_id FROM eval_run) "
        "GROUP BY d.run_id ORDER BY bytes DESC").fetchall()
    total_rows = sum(r["n"] for r in orphans)
    total_bytes = sum(r["bytes"] or 0 for r in orphans)
    print(f"孤儿明细: {total_rows} 行 / {_mb(total_bytes)} MB / {len(orphans)} 个已删除的 run")
    for r in orphans[:10]:
        print(f"   - {r['run_id']}  {r['n']} 行  {_mb(r['bytes'])} MB")


def purge_orphans(conn: sqlite3.Connection, apply: bool) -> int:
    rows = conn.execute(
        "SELECT run_id FROM eval_run_detail WHERE run_id NOT IN (SELECT run_id FROM eval_run)"
    ).fetchall()
    if not rows:
        print("孤儿明细: 无")
        return 0
    if not apply:
        print(f"孤儿明细: 待删 {len(rows)} 行（加 --purge-orphans 才真删）")
        return 0
    cursor = conn.execute(
        "DELETE FROM eval_run_detail WHERE run_id NOT IN (SELECT run_id FROM eval_run)")
    conn.commit()
    print(f"孤儿明细: 已删 {cursor.rowcount} 行")
    return cursor.rowcount


def stale_runs(conn: sqlite3.Connection, days: int):
    """返回 (run 行列表, 保留下限日期)。保留口径与 nightly 归档一致：今天 + 前 days-1 天。"""
    floor = datetime.now(BJT).date() - timedelta(days=max(days - 1, 0))
    stale = []
    for row in conn.execute(
            "SELECT run_id, dataset_id, started_at, status, is_full_run FROM eval_run"):
        day = _bjt_date(row["started_at"])
        if day is not None and day < floor:
            stale.append((row, day))
    return stale, floor


def purge_stale_runs(conn: sqlite3.Connection, days: int, apply: bool) -> int:
    stale, floor = stale_runs(conn, days)
    print(f"整轮 run : 保留 {floor} 及以后；早于该日的 {len(stale)} 轮：")
    for row, day in stale:
        size = conn.execute(
            f"SELECT COUNT(*) AS n, SUM({PAYLOAD}) AS bytes FROM eval_run_detail WHERE run_id = ?",
            (row["run_id"],)).fetchone()
        print(f"   - {day} {row['run_id']} {row['dataset_id']} status={row['status']} "
              f"{size['n']} 行 {_mb(size['bytes'])} MB")
    if not stale or not apply:
        if stale:
            print("   （加 --older-than-days N 且不带 --dry-run 才会删）")
        return 0
    ids = [row["run_id"] for row, _ in stale]
    placeholders = ",".join("?" for _ in ids)
    details = conn.execute(
        f"DELETE FROM eval_run_detail WHERE run_id IN ({placeholders})", ids).rowcount
    conn.execute(f"DELETE FROM eval_run WHERE run_id IN ({placeholders})", ids)
    conn.commit()
    print(f"   → 已删 {len(ids)} 轮 run、{details} 行明细")
    return len(ids)


def vacuum(conn: sqlite3.Connection, db: Path) -> None:
    before = db.stat().st_size
    conn.commit()
    conn.isolation_level = None  # VACUUM 不能在事务里
    print("VACUUM 中（独占写锁，请勿并发评测）…")
    conn.execute("VACUUM")
    after = db.stat().st_size
    print(f"VACUUM 完成：{_size(before)} → {_size(after)}（回收 {_size(before - after)}）")


def main() -> int:
    parser = argparse.ArgumentParser(description="evals.sqlite 体检 / 孤儿明细回收 / VACUUM")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"库路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--purge-orphans", action="store_true", help="删除父 run 已不存在的明细行")
    parser.add_argument("--older-than-days", type=int, default=0,
                        help="整轮 run 保留天数（含当天）；>0 时删除更早的整轮 run 及其明细")
    parser.add_argument("--vacuum", action="store_true", help="回收空间还给文件系统（独占写锁）")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要删除的内容，不落删除")
    args = parser.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"找不到库文件：{db}", flush=True)
        return 2
    apply = not args.dry_run
    conn = _connect(db)
    try:
        report(conn, db)
        print()
        print("== 处置 ==")
        purge_orphans(conn, apply)
        if args.older_than_days > 0:
            purge_stale_runs(conn, args.older_than_days, apply)
        if args.vacuum:
            vacuum(conn, db)
        elif apply:
            print("提示：删除不会让文件变小，需再跑 --vacuum（或等 SQLite 复用空闲页）。")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
