"""把 DMS 导入清单里的路径元数据回填进 doc_catalog（不重跑解析，只写元数据）。

背景：lab-firm-full 快车道导入只把文件名当 title 上传，matter 目录在入库时丢了；
而官方 harness 的 agent 能直接看到 dms/matters/<matter>/<folder>/<file> 目录树。
枚举型题目（「列出所有 X 的 matter」）需要这层路径信息，否则只能靠正文猜。

本脚本把 full_import_manifest.jsonl 的 (rel, tier, doc_id) 写进对应库组的
index sqlite 的 doc_catalog 表（CREATE TABLE IF NOT EXISTS，不迁移既有表）。

用法：
    python scripts/backfill_doc_catalog.py --library lab-firm-full \
        --manifest data/scratch/harvey-lab/full_import_manifest.jsonl --dry-run
    python scripts/backfill_doc_catalog.py --library lab-firm-full \
        --manifest data/scratch/harvey-lab/full_import_manifest.jsonl

清单字段约定：rel=相对路径（matter/folder/file），tier=matter id，doc_id=库内文档 id；
可用 --rel-key/--matter-key/--doc-key 改。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))


def load_rows(path: Path, rel_key: str, matter_key: str, doc_key: str, library_id: str) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            doc_id = str(obj.get(doc_key) or "").strip()
            rel = str(obj.get(rel_key) or "").strip()
            if not doc_id or not rel:
                continue
            parts = [p for p in rel.replace("\\", "/").split("/") if p]
            matter = str(obj.get(matter_key) or (parts[0] if parts else "")).strip()
            filename = parts[-1] if parts else ""
            folder = "/".join(parts[1:-1]) if len(parts) > 2 else ""
            rows.append({
                "doc_id": doc_id,
                "library_id": library_id,
                "matter_id": matter,
                "folder": folder,
                "rel_path": rel,
                "filename": filename,
                "doc_type": Path(filename).suffix.lower().lstrip("."),
                "source": "import_manifest",
                "updated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", required=True)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--rel-key", default="rel")
    ap.add_argument("--matter-key", default="tier")
    ap.add_argument("--doc-key", default="doc_id")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from docs_core.library_registry import resolve_index_db_path
    from docs_core.step09_query.doc_search import ensure_catalog, has_catalog

    import sqlite3

    rows = load_rows(Path(args.manifest), args.rel_key, args.matter_key, args.doc_key, args.library)
    db_path = resolve_index_db_path(args.library)
    print(f"library={args.library} db={db_path} manifest_rows={len(rows)}")
    print("first:", rows[0] if rows else None)
    if args.dry_run:
        return 0

    conn = sqlite3.connect(str(db_path), timeout=30.0)
    try:
        ensure_catalog(conn)
        existing = {r[0] for r in conn.execute("select doc_id from doc_catalog where library_id=?", (args.library,))}
        todo = [r for r in rows if r["doc_id"] not in existing]
        conn.executemany(
            "insert or replace into doc_catalog(doc_id, library_id, matter_id, folder, rel_path, filename, doc_type, source, updated_at) "
            "values(:doc_id, :library_id, :matter_id, :folder, :rel_path, :filename, :doc_type, :source, :updated_at)",
            todo,
        )
        conn.commit()
        total = conn.execute("select count(*) from doc_catalog where library_id=?", (args.library,)).fetchone()[0]
        matters = conn.execute(
            "select count(distinct matter_id) from doc_catalog where library_id=?", (args.library,)
        ).fetchone()[0]
    finally:
        conn.close()
    print(f"inserted={len(todo)} catalog_rows={total} matters={matters}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
