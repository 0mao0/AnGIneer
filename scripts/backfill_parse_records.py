"""回填 parse_records 流水：把"只进 nodes 没进流水"的存量文档补上记录。

背景（2026-09-14）：parse_records 以前只由 docs-api 注入的 record_updater 写，脚本/进程内
路径（语料导入、评测 in-process）没注入 → 文档只进 knowledge_meta.nodes，管理端「日常维护」
整篇看不见（实测盘上 295 篇有 189 篇不在流水：lib-b07ed174 115 篇、lawbench 60 篇等）。
代码侧已把默认实现下沉到 `docs_core.parse_records_store`（以后不再发生）；本脚本负责存量。

口径：
- 只补 `nodes` 里 type=document、deleted=0、且 parse_records 里没有该 doc_id 的文档；
- task_id 取该文档最新一条 parse_tasks 的 id，没有则 `backfill-<doc_id>`（保持可追溯）；
- status 取最新 parse_task 的 status，没有则退回 node.status；
- created_at 取该文档**最早**一条 parse_task 的创建时间（近似上传时间），退回 node.created_at；
- file_name 用 node.title；大小/格式来自源文件实测（node.file_path 是容器内路径
  `/app/data/...`，按 "libraries/" 之后的部分拼回宿主 data 目录，与部署布局无关）；
- uploaded_by 默认 `system:backfill`，用于和界面/API 上传区分。

幂等：已有记录的 doc_id 一律跳过，可重复运行。

用法（服务器上直接跑，默认路径即宿主机 data 目录）：
    python3 scripts/backfill_parse_records.py --dry-run
    python3 scripts/backfill_parse_records.py
"""
import argparse
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DATA_ROOT = Path("/home/runner/AnGIneer/data")


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _source_path(file_path: str, library_id: str, doc_id: str, data_root: Path) -> Path:
    """定位源文件：优先按 file_path 里的 libraries/... 段拼回宿主路径，其次扫 source/ 目录。"""
    raw = str(file_path or "")
    if "libraries/" in raw:
        cand = data_root / raw[raw.index("libraries/"):]
        if cand.is_file():
            return cand
    src_dir = data_root / "knowledge_base" / "libraries" / library_id / "documents" / doc_id / "source"
    if src_dir.is_dir():
        files = sorted(f for f in src_dir.glob("*") if f.is_file())
        if files:
            return files[0]
    return Path(raw)


def collect(meta: sqlite3.Connection, have: set, data_root: Path, actor: str) -> list:
    node_cols = [c[1] for c in meta.execute("PRAGMA table_info(nodes)")]
    nodes = [dict(zip(node_cols, r)) for r in meta.execute("SELECT * FROM nodes")]
    tasks: dict = {}
    for tid, doc_id, status, created_at in meta.execute(
            "SELECT id, doc_id, status, created_at FROM parse_tasks ORDER BY created_at ASC"):
        tasks.setdefault(doc_id, []).append({"id": tid, "status": status, "created_at": created_at})

    rows = []
    for node in nodes:
        doc_id = str(node.get("id") or "")
        if not doc_id or doc_id in have:
            continue
        if str(node.get("type") or "") != "document" or int(node.get("deleted") or 0):
            continue
        library_id = str(node.get("library_id") or "default")
        bucket = tasks.get(doc_id) or []
        latest = bucket[-1] if bucket else {}
        earliest = bucket[0] if bucket else {}
        src = _source_path(node.get("file_path") or "", library_id, doc_id, data_root)
        file_name = str(node.get("title") or "") or src.name
        rows.append({
            "doc_id": doc_id,
            "task_id": str(latest.get("id") or f"backfill-{doc_id}"),
            "uploaded_by": actor,
            "file_name": file_name,
            "file_format": os.path.splitext(file_name)[1].lstrip(".").lower(),
            "file_size": src.stat().st_size if src.is_file() else 0,
            "status": str(latest.get("status") or node.get("status") or "completed"),
            "created_at": str(earliest.get("created_at") or node.get("created_at") or _iso_now()),
            "library_id": library_id,
            "stages": "",
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="回填 parse_records 流水（存量文档）")
    ap.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT), help="宿主 data 目录")
    ap.add_argument("--meta-db", default="", help="knowledge_meta.sqlite（默认 <data-root>/knowledge_base/）")
    ap.add_argument("--records-db", default="", help="parse_records.sqlite（默认 <data-root>/）")
    ap.add_argument("--actor", default="system:backfill", help="回填记录的 uploaded_by")
    ap.add_argument("--dry-run", action="store_true", help="只打印将要补的条数，不写库")
    args = ap.parse_args()

    data_root = Path(args.data_root)
    meta_db = Path(args.meta_db) if args.meta_db else data_root / "knowledge_base" / "knowledge_meta.sqlite"
    records_db = Path(args.records_db) if args.records_db else data_root / "parse_records.sqlite"
    for p in (meta_db, records_db):
        if not p.is_file():
            raise SystemExit(f"文件不存在: {p}")

    meta = sqlite3.connect(f"file:{meta_db}?mode=ro", uri=True)
    rec = sqlite3.connect(f"file:{records_db}?mode=ro", uri=True)
    try:
        have = {r[0] for r in rec.execute("SELECT doc_id FROM parse_records")}
        rows = collect(meta, have, data_root, args.actor)
    finally:
        meta.close()
        rec.close()

    by_lib = Counter(r["library_id"] for r in rows)
    no_task = sum(1 for r in rows if r["task_id"].startswith("backfill-"))
    no_size = sum(1 for r in rows if not r["file_size"])
    print(f"待回填 {len(rows)} 篇（其中 {no_task} 篇无 parse_task、{no_size} 篇未量到源文件大小）")
    for lib, n in by_lib.most_common():
        print(f"  {lib:20} {n:>4}")
    if args.dry_run:
        print("--dry-run：未写库")
        for r in rows[:3]:
            print("   样例:", {k: str(v)[:44] for k, v in r.items()})
        return 0

    # 只做 INSERT，不建表：表结构归 docs_core.parse_records_store（避免第二份 DDL）
    conn = sqlite3.connect(str(records_db))
    try:
        columns = {r[1] for r in conn.execute("PRAGMA table_info(parse_records)")}
        needed = {"doc_id", "task_id", "uploaded_by", "api_key_id", "file_name", "file_format",
                  "file_size", "status", "error", "created_at", "library_id", "stages"}
        missing = needed - columns
        if missing:
            raise SystemExit(f"parse_records 缺列 {sorted(missing)}：先跑一次解析建表再回填")
        for r in rows:
            conn.execute(
                """INSERT INTO parse_records (doc_id, task_id, uploaded_by, api_key_id,
                   file_name, file_format, file_size, status, error, created_at, library_id, stages)
                   VALUES (?, ?, ?, NULL, ?, ?, ?, ?, NULL, ?, ?, ?)""",
                (r["doc_id"], r["task_id"], r["uploaded_by"], r["file_name"], r["file_format"],
                 r["file_size"], r["status"], r["created_at"], r["library_id"], r["stages"]),
            )
        conn.commit()
    finally:
        conn.close()
    print(f"已回填 {len(rows)} 篇 → {records_db}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
