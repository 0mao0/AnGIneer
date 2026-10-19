"""为所有库建立 doc_catalog 并物化语义字段（不重跑解析）。

做两件事：
1. 从 meta 库 nodes 建目录行：doc_id / library_id / filename（= nodes.title）；
   已有行不覆盖（lab-firm-full 的 matter/路径元数据保留）；
2. 调 backfill_semantic_fields：从 doc_blocks 首屏 title 块物化 title_semantic + doc_type_semantic。

用法：
    python scripts/backfill_catalog_all.py --dry-run
    python scripts/backfill_catalog_all.py
    python scripts/backfill_catalog_all.py --library std-water --library std-highway
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", action="append", default=[], help="只处理指定库（可重复）")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from docs_core.library_registry import list_libraries, resolve_index_db_path
    from docs_core.paths import resolve_knowledge_meta_db_path
    from docs_core.step09_query.doc_search import (
        backfill_semantic_fields,
        catalog_semantic_coverage,
        ensure_catalog,
    )

    meta_path = resolve_knowledge_meta_db_path()
    meta = sqlite3.connect(f"file:{meta_path}?mode=ro", uri=True)
    meta.row_factory = sqlite3.Row

    libs = [r.library_id for r in list_libraries()]
    if args.library:
        libs = [x for x in libs if x in set(args.library)]
    print(f"libraries={len(libs)} meta={meta_path}")
    rows = []
    for lib in libs:
        try:
            db = resolve_index_db_path(lib)
        except Exception as exc:  # noqa: BLE001
            print(f"{lib}: resolve ERR {exc}")
            continue
        if not db.exists():
            print(f"{lib}: no index db")
            continue
        nodes = meta.execute(
            "select id, title from nodes where library_id=? and deleted=0", (lib,)
        ).fetchall()
        rows.append((lib, db, nodes))

    if args.dry_run:
        for lib, db, nodes in rows:
            print(f"{lib}: nodes={len(nodes)} db={db}")
        return 0

    t0 = time.time()
    for lib, db, nodes in rows:
        conn = sqlite3.connect(str(db), timeout=30)
        conn.row_factory = sqlite3.Row
        try:
            ensure_catalog(conn)
            existing = {r[0] for r in conn.execute("select doc_id from doc_catalog where library_id=?", (lib,))}
            todo = [
                (n["id"], lib, "", "", "", n["title"] or "", "", "meta_nodes",
                 time.strftime("%Y-%m-%dT%H:%M:%S"))
                for n in nodes
                if n["id"] not in existing
            ]
            conn.executemany(
                "insert or ignore into doc_catalog(doc_id, library_id, matter_id, folder, rel_path, "
                "filename, doc_type, source, updated_at) values (?,?,?,?,?,?,?,?,?)",
                todo,
            )
            conn.commit()
            stats = backfill_semantic_fields(conn, lib)
            cov = catalog_semantic_coverage(conn, lib)
            print(f"{lib}: nodes={len(nodes)} inserted={len(todo)} {cov}")
        except Exception as exc:  # noqa: BLE001
            print(f"{lib}: ERR {type(exc).__name__}: {exc}")
        finally:
            conn.close()
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
