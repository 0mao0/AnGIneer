"""数据库一致性快照工具：VACUUM INTO + 打开即校验 + 代数轮转。

为什么不用 cp：
    生产库全部是 WAL 模式（`PRAGMA journal_mode=WAL`）。对运行中的 WAL 库做文件级
    复制会丢掉尚未 checkpoint 的已提交事务——服务器上 evals 的 -wal 实测到过 1.38 GB。
    2026-10-02 发现的一份 646 MB 手工副本（archive/server-backup-20260908/…pm）
    已损坏到连 sqlite_master 都读不出来，躺了约四周无人察觉。本脚本用 SQLite 官方的
    `VACUUM INTO` 产出**一致的单一文件**快照，并对每个快照做「打开 + 完整性 + 行数对账」。

用法（仓库根目录执行；容器内路径同构）：
    python scripts/db_snapshot.py                          # 全部活库，默认保留 2 代
    python scripts/db_snapshot.py --only knowledge_meta    # 只做一库
    python scripts/db_snapshot.py --out-dir /mnt/backup    # 快照落到别处（推荐异地）
    python scripts/db_snapshot.py --keep 3                 # 每库保留 3 代
    python scripts/db_snapshot.py --list                   # 只列活库路径与体积，不备份
    python scripts/db_snapshot.py --verify-only path.sqlite  # 校验任意快照/备份是否可用

磁盘提示：快照体积约等于源库大小（VACUUM 会回收 freelist，通常略小）。部署机根分区
只剩 6.7 GB 时放不下 knowledge_index(3.4G)+evals(3.9G) 的全套快照，必须一库一传地
落到异地，或只保留小库的本地代。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------- 活库登记表
# 路径口径与运行时代码一致：优先 env 覆盖，否则仓库 data/ 下的默认位置。
REPO_ROOT = Path(__file__).resolve().parents[1]


def _p(env_key: str, default_rel: str) -> Path:
    raw = (os.getenv(env_key) or "").strip()
    return Path(raw).expanduser() if raw else REPO_ROOT / default_rel


LIVE_DBS: Dict[str, Path] = {
    "knowledge_meta": _p("KNOWLEDGE_META_DB_PATH", "data/knowledge/knowledge_meta.sqlite"),
    "knowledge_index": _p("KNOWLEDGE_INDEX_DB_PATH", "data/knowledge/knowledge_index.sqlite"),
    "knowledge_graph": _p("KNOWLEDGE_GRAPH_DB_PATH", "data/knowledge/graph.sqlite"),
    "parse_records": _p("PARSE_RECORDS_DB_PATH", "data/knowledge/parse_records.sqlite"),
    "api_keys": _p("API_KEYS_DB_PATH", "data/api_keys.sqlite"),
    "users": _p("USERS_DB_PATH", "data/users.sqlite"),
    "chat": _p("CHAT_DB_PATH", "data/platform/chat.sqlite"),
    "evals": _p("EVALS_DB_PATH", "data/evals/evals.sqlite"),
}


def _group_dbs() -> Dict[str, Path]:
    """组文件按库动态增长（groups/ 下一库一个 .sqlite），glob 登记。

    只收 *.sqlite 终态文件：-wal/-shm 由 VACUUM INTO 一并固化，bak 是历史残留。
    快照缺组文件=备份静默不完整（2026-10-06 计划二轮评审钉死，勿再漏）。
    """
    entries: Dict[str, Path] = {}
    for domain, rel in (("kn", "data/knowledge/groups"), ("ev", "data/evals/groups")):
        for path in sorted((REPO_ROOT / rel).glob("*.sqlite")):
            entries[f"group_{domain}_{path.stem}"] = path
    return entries


LIVE_DBS.update(_group_dbs())

MB = 1024 * 1024


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _connect_readonly(path: Path, timeout: float) -> sqlite3.Connection:
    """优先只读打开；个别环境不接受只读连接跑 VACUUM INTO 时退回普通连接（仍不写源库）。"""
    try:
        conn = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=timeout)
        conn.execute("SELECT count(*) FROM sqlite_master").fetchone()
        return conn
    except sqlite3.Error:
        return sqlite3.connect(str(path), timeout=timeout)


def _table_counts(conn: sqlite3.Connection) -> Dict[str, int]:
    """各表行数（跳过 FTS5 影子表，它们随主表联动、体积大且对账无意义）。"""
    names = [
        row[0]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
    ]
    shadow = set()
    for name in names:
        if name.endswith(("_data", "_idx", "_content", "_docsize", "_config")):
            shadow.add(name)
    counts: Dict[str, int] = {}
    for name in names:
        if name in shadow:
            continue
        try:
            counts[name] = conn.execute(f'SELECT count(*) FROM "{name}"').fetchone()[0]
        except sqlite3.Error:
            continue
    return counts


def _quick_check(conn: sqlite3.Connection) -> str:
    try:
        return str(conn.execute("PRAGMA quick_check(1)").fetchone()[0])
    except sqlite3.Error as exc:
        return f"quick_check 失败: {exc}"


def verify_snapshot(snapshot: Path, source: Optional[Path] = None) -> Dict[str, object]:
    """打开快照做完整性检查；给了 source 就再逐表对账行数。

    对账差异不算损坏：源库是活的，写完快照后仍会继续写。差异只作为 INFO 报出。
    """
    result: Dict[str, object] = {"snapshot": str(snapshot), "size_mb": round(_size(snapshot) / MB, 1)}
    if not snapshot.exists():
        result["ok"] = False
        result["error"] = "文件不存在"
        return result
    try:
        conn = sqlite3.connect(f"file:{snapshot.as_posix()}?mode=ro", uri=True, timeout=60)
    except sqlite3.Error as exc:
        result["ok"] = False
        result["error"] = f"打不开: {exc}"
        return result
    try:
        # 校验器自己必须扛得住坏文件：损坏的备份正是本工具要防的头号情况，
        # 它不能以 traceback 收场——夜间靠退出码与 JSON 的 ok=false 报警。
        try:
            check = _quick_check(conn)
        except sqlite3.Error as exc:
            result["ok"] = False
            result["error"] = f"完整性检查无法执行: {exc}"
            return result
        result["quick_check"] = check
        if check != "ok":
            result["ok"] = False
            result["error"] = f"完整性检查未通过: {check}"
            return result
        try:
            snap_counts = _table_counts(conn)
        except sqlite3.Error as exc:
            result["ok"] = False
            result["error"] = f"读取失败（文件损坏或不是 SQLite 库）: {exc}"
            return result
        result["tables"] = len(snap_counts)
        result["rows"] = sum(snap_counts.values())
        if not snap_counts:
            result["ok"] = False
            result["error"] = "快照里没有任何表（可能是空文件或截断）"
            return result
        if source is not None and source.exists():
            src_counts: Optional[Dict[str, int]] = None
            try:
                src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=60)
                try:
                    src_counts = _table_counts(src)
                finally:
                    src.close()
            except sqlite3.Error as exc:
                # 源库读不了不该让快照校验失败，如实记一笔即可
                result["source_read_error"] = str(exc)
            if src_counts is not None:
                diff = {
                    name: {"source": src_counts.get(name), "snapshot": snap_counts.get(name)}
                    for name in set(src_counts) | set(snap_counts)
                    if src_counts.get(name) != snap_counts.get(name)
                }
                result["diff_tables"] = len(diff)
                if diff:
                    result["diff_sample"] = dict(list(diff.items())[:5])
        result["ok"] = True
        return result
    finally:
        conn.close()


def snapshot_one(name: str, source: Path, out_dir: Path, keep: int,
                 verify: bool, timeout: float) -> Dict[str, object]:
    info: Dict[str, object] = {"name": name, "source": str(source)}
    if not source.exists():
        info["ok"] = False
        info["error"] = "源库不存在"
        return info
    src_mb = _size(source) / MB
    info["source_mb"] = round(src_mb, 1)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"{name}-{stamp}.sqlite"
    if target.exists():
        target.unlink()

    started = time.time()
    try:
        conn = _connect_readonly(source, timeout)
        try:
            conn.isolation_level = None  # VACUUM 不能在事务里
            conn.execute("VACUUM INTO ?", (str(target),))
        finally:
            conn.close()
    except sqlite3.Error as exc:
        info["ok"] = False
        info["error"] = f"VACUUM INTO 失败: {exc}"
        if target.exists():
            target.unlink()
        return info
    info["elapsed_s"] = round(time.time() - started, 1)
    info["snapshot"] = str(target)
    info["snapshot_mb"] = round(_size(target) / MB, 1)

    if verify:
        check = verify_snapshot(target, source if src_mb > 0 else None)
        info["verify"] = check
        info["ok"] = bool(check.get("ok"))
        if not info["ok"]:
            # 校验没过就别留着冒充备份
            info["error"] = f"校验未通过，已删除: {check.get('error')}"
            try:
                target.unlink()
            except OSError:
                pass
            return info
    else:
        info["ok"] = True

    removed = _rotate(name, out_dir, keep)
    if removed:
        info["rotated_out"] = [p.name for p in removed]
    return info


def _rotate(name: str, out_dir: Path, keep: int) -> List[Path]:
    """每库按文件名时间戳保留最近 keep 代（keep<=0 表示不轮转）。"""
    if keep <= 0:
        return []
    existing = sorted(out_dir.glob(f"{name}-*.sqlite"), key=lambda p: p.name)
    removed: List[Path] = []
    while len(existing) > keep:
        victim = existing.pop(0)
        try:
            victim.unlink()
            removed.append(victim)
        except OSError:
            pass
    return removed


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="SQLite 一致性快照（VACUUM INTO）+ 校验 + 轮转")
    ap.add_argument("--only", action="append", default=None,
                    help="只处理指定库，可重复；库名见 --list")
    ap.add_argument("--out-dir", default=str(REPO_ROOT / "data" / "backups" / "snapshots"),
                    help="快照目录（生产建议指到异地/挂载卷）")
    ap.add_argument("--keep", type=int, default=2, help="每库保留代数，0=不轮转（默认 2）")
    ap.add_argument("--no-verify", action="store_true", help="跳过打开即校验（不推荐）")
    ap.add_argument("--timeout", type=float, default=120.0, help="打开源库的等待秒数")
    ap.add_argument("--list", action="store_true", help="只列活库与体积")
    ap.add_argument("--verify-only", default="", help="只校验指定快照文件，不备份")
    ap.add_argument("--json", action="store_true", help="输出 JSON 摘要")
    args = ap.parse_args(argv)

    if args.verify_only:
        out = verify_snapshot(Path(args.verify_only))
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 0 if out.get("ok") else 1

    targets = {k: v for k, v in LIVE_DBS.items() if not args.only or k in args.only}
    unknown = [k for k in (args.only or []) if k not in LIVE_DBS]
    if unknown:
        print(f"未知库名: {', '.join(unknown)}；可选: {', '.join(LIVE_DBS)}", file=sys.stderr)
        return 2

    if args.list:
        for name, path in sorted(targets.items()):
            exists = "存在" if path.exists() else "缺失"
            print(f"{name:16} {_size(path)/MB:9.1f} MB  {exists}  {path}")
        return 0

    out_dir = Path(args.out_dir)
    results = []
    for name, path in sorted(targets.items()):
        info = snapshot_one(name, path, out_dir, args.keep, not args.no_verify, args.timeout)
        results.append(info)
        if not args.json:
            if info.get("ok"):
                v = info.get("verify") or {}
                extra = ""
                if v.get("diff_tables"):
                    extra = f"  行数差异表={v['diff_tables']}（源库在快照后继续写，属正常）"
                print(f"[ok  ] {name:16} {info['source_mb']:8.1f} MB -> {info['snapshot_mb']:8.1f} MB"
                      f"  用时 {info.get('elapsed_s')}s  quick_check={v.get('quick_check')}{extra}")
            else:
                print(f"[FAIL] {name:16} {info.get('error')}")

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    failed = [r["name"] for r in results if not r.get("ok")]
    if failed:
        print(f"\n失败的库: {', '.join(failed)}", file=sys.stderr)
        return 1
    total = sum(float(r.get("snapshot_mb") or 0) for r in results)
    if not args.json:
        print(f"\n共 {len(results)} 个库，快照合计 {total:.1f} MB，目录 {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
