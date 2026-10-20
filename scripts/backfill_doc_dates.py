"""回填 doc_catalog 的文档日期（时间维度，不重跑解析）。

做一件事：对每个库的 doc_catalog 行，按「正文首屏日期 > 文件名日期 > 源文件 mtime」
抽 doc_date / date_source / date_confidence，批量 UPDATE，并打印覆盖分布。

用法：
    python scripts/backfill_doc_dates.py --dry-run
    python scripts/backfill_doc_dates.py
    python scripts/backfill_doc_dates.py --library lab-firm-full
    python scripts/backfill_doc_dates.py --library lab-firm-full --limit 200
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--library", action="append", default=[], help="只处理指定库（可重复）")
    ap.add_argument("--limit", type=int, default=0, help="每库最多处理多少篇（0=全部，冒烟用）")
    ap.add_argument("--dry-run", action="store_true", help="只列出将要处理的库")
    args = ap.parse_args()

    from docs_core.library_registry import list_libraries, resolve_index_db_path
    from docs_core.step09_query.doc_search import backfill_doc_dates, catalog_date_coverage

    libs = [r.library_id for r in list_libraries()]
    if args.library:
        libs = [x for x in libs if x in set(args.library)]
    print(f"libraries={len(libs)}")
    targets = []
    for lib in libs:
        try:
            db = resolve_index_db_path(lib)
        except Exception as exc:  # noqa: BLE001
            print(f"{lib}: resolve ERR {exc}")
            continue
        if not db.exists():
            print(f"{lib}: no index db")
            continue
        targets.append((lib, db))

    if args.dry_run:
        for lib, db in targets:
            print(f"{lib}: db={db}")
        return 0

    t0 = time.time()
    for lib, db in targets:
        try:
            stats = backfill_doc_dates(lib, limit=args.limit or None)
        except Exception as exc:  # noqa: BLE001
            print(f"{lib}: ERR {type(exc).__name__}: {exc}")
            continue
        print(f"{lib}: {stats}")
        try:
            from docs_core.step09_query.doc_search import _connect

            conn = _connect(lib)
            try:
                print(f"{lib}: coverage {catalog_date_coverage(conn, lib)}")
            finally:
                conn.close()
        except Exception as exc:  # noqa: BLE001
            print(f"{lib}: coverage ERR {exc}")
    print(f"done in {time.time() - t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
