"""向量数据迁移：canonical_vectors (SQLite) → Qdrant。

适用场景：DOCS_VECTORSTORE_PROVIDER 从 sqlite 切换到 qdrant 前的存量数据搬迁。
直接复制已有 embedding（不重新调用 embedding 端点，223k 向量分钟级完成）。
迁移期间旧引擎照常在线，本脚本只读 SQLite、只写 Qdrant，互不影响。

特性：
- rowid 游标分批流式读取（与向量缓存同款分批模式，5GB 级库不 OOM）
- 断点续传：进度落 <knowledge_base>/qdrant_migration_progress.json
- 空向量行跳过（Qdrant 不承载零向量，与 QdrantVectorStore 语义一致）
- --reset 删除并重建 collection（重复迁移/换维时用）

用法（本机或 docs-api 容器内）：
    python scripts/migrate_vectors_to_qdrant.py              # DRY RUN 预览
    python scripts/migrate_vectors_to_qdrant.py --yes        # 执行迁移（断点续跑）
    python scripts/migrate_vectors_to_qdrant.py --yes --reset   # 清空 Qdrant 重新全量迁移
"""
import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _index_db_path() -> Path:
    """与 docs_core.paths 口径一致，但不触发 docs_core 导入。"""
    base = os.getenv("KNOWLEDGE_BASE_DIR", "").strip()
    if not base:
        for candidate in ("/app/data/knowledge_base",):
            if Path(candidate).exists():
                base = candidate
                break
    if not base:
        base = str(Path(__file__).resolve().parents[1] / "data" / "knowledge_base")
    return Path(base) / "knowledge_index.sqlite"


def _load_progress(progress_path: Path) -> dict:
    if progress_path.exists():
        try:
            return json.loads(progress_path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_rowid": 0, "migrated": 0, "skipped_empty": 0}


def main() -> int:
    parser = argparse.ArgumentParser(description="canonical_vectors → Qdrant 迁移")
    parser.add_argument("--yes", action="store_true", help="确认执行（缺省为 DRY RUN）")
    parser.add_argument("--reset", action="store_true", help="删除并重建 Qdrant collection 后全量迁移")
    parser.add_argument("--batch-size", type=int, default=2048, help="每批读取/写入条数")
    parser.add_argument("--limit", type=int, default=0, help="只迁移前 N 条（冒烟验证用）")
    args = parser.parse_args()

    db_path = _index_db_path()
    if not db_path.exists():
        print(f"[migrate] 向量库不存在: {db_path}", flush=True)
        return 1
    progress_path = db_path.parent / "qdrant_migration_progress.json"

    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    total_rows = conn.execute("SELECT COUNT(*) FROM canonical_vectors").fetchone()[0]
    nonempty_rows = conn.execute(
        "SELECT COUNT(*) FROM canonical_vectors WHERE dimension > 0"
    ).fetchone()[0]
    dim_row = conn.execute(
        "SELECT dimension, COUNT(*) FROM canonical_vectors WHERE dimension > 0"
        " GROUP BY dimension ORDER BY COUNT(*) DESC"
    ).fetchall()
    print(f"[migrate] 源库 {db_path}", flush=True)
    print(f"[migrate] 总行数 {total_rows}，有效向量 {nonempty_rows}，维度分布 {dim_row}", flush=True)
    if not args.yes:
        print("[migrate] DRY RUN：加 --yes 才会真正执行", flush=True)
        conn.close()
        return 2

    from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore
    from docs_core.step06_vectors.vector_store import VectorRecord

    store = QdrantVectorStore()
    if args.reset:
        try:
            store._get_client().delete_collection(store._collection)
            print(f"[migrate] 已删除 collection {store._collection}（--reset）", flush=True)
        except Exception:
            pass
        store._expected_dim = None
        progress_path.unlink(missing_ok=True)

    progress = _load_progress(progress_path)
    last_rowid = int(progress.get("last_rowid") or 0)
    migrated = int(progress.get("migrated") or 0)
    skipped_empty = int(progress.get("skipped_empty") or 0)
    if last_rowid:
        print(f"[migrate] 断点续跑：rowid > {last_rowid}，已迁移 {migrated} 条", flush=True)

    started = time.perf_counter()
    batch: list = []
    cursor = conn.execute(
        "SELECT rowid, record_id, doc_id, entity_type, entity_id, content, content_hash,"
        " metadata_json, embedding_json FROM canonical_vectors WHERE rowid > ? ORDER BY rowid",
        (last_rowid,),
    )
    processed = 0
    for row in cursor:
        last_rowid = int(row[0])
        try:
            embedding = json.loads(row[8]) if row[8] else []
        except Exception:
            embedding = []
        if not embedding:
            skipped_empty += 1
            continue
        try:
            metadata = json.loads(row[7]) if row[7] else {}
        except Exception:
            metadata = {}
        batch.append(
            VectorRecord(
                record_id=row[1],
                doc_id=row[2],
                entity_type=row[3],
                entity_id=row[4],
                content=row[5] or "",
                content_hash=row[6] or "",
                metadata=metadata,
                embedding=embedding,
            )
        )
        if len(batch) >= args.batch_size:
            store.upsert_records(batch)
            migrated += len(batch)
            processed += len(batch)
            batch = []
            progress_path.write_text(
                json.dumps(
                    {"last_rowid": last_rowid, "migrated": migrated, "skipped_empty": skipped_empty},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            elapsed = time.perf_counter() - started
            rate = migrated / elapsed if elapsed > 0 else 0
            print(
                f"[migrate] 已迁移 {migrated}/{nonempty_rows}（{rate:.0f} 条/s，rowid={last_rowid}）",
                flush=True,
            )
        if args.limit and migrated + len(batch) >= args.limit:
            break
    if batch:
        store.upsert_records(batch)
        migrated += len(batch)
    progress_path.write_text(
        json.dumps(
            {"last_rowid": last_rowid, "migrated": migrated, "skipped_empty": skipped_empty},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    conn.close()

    qdrant_total = store.get_global_stats()["total_rows"]
    elapsed = time.perf_counter() - started
    print(f"[migrate] 完成：迁移 {migrated} 条，跳过空向量 {skipped_empty} 条，耗时 {elapsed:.1f}s", flush=True)
    print(f"[migrate] Qdrant collection 当前总量 {qdrant_total} 条（源库有效向量 {nonempty_rows} 条）", flush=True)
    if args.limit:
        print("[migrate] 注意：本次为 --limit 冒烟迁移，全量迁移请去掉 --limit 续跑", flush=True)
        return 0
    if qdrant_total != nonempty_rows:
        print("[migrate] 警告：两侧数量不一致，请检查是否有失败批次后重跑（幂等，可直接重跑）", flush=True)
        return 1
    print("[migrate] 数量核对一致 [OK]", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
