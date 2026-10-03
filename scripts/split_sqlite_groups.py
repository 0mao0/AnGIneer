"""sqlite 按组拆文件：knowledge_index.sqlite → 各组文件（正文+FTS+doc_blocks+segments）。

承接 docs/plan-kb-split-groups.md 阶段二前半。特性：
- ATTACH 源库 + 临时 doc 集合表 + INSERT SELECT，不逐行 Python 搬运
- FTS 直接复制行（text_ngrams 已在源行内，不重算）
- 幂等：每组先按 doc 集合 DELETE 再 INSERT，中断重跑无重复
- 零停机：seed 时 sqlite_file 仍挂单文件（路由不变），本脚本搬完 + --verify 后
  用 --flip-sqlite 翻转注册表（原子切换），--prune-source 清源留待回滚窗口终点

用法（本机或 docs-api 容器内）：
    python scripts/split_sqlite_groups.py                 # DRY RUN：各组各表应迁行数预览
    python scripts/split_sqlite_groups.py --yes           # 执行搬迁
    python scripts/split_sqlite_groups.py --verify        # 对账：各组各表 目标 == 源应收
    python scripts/split_sqlite_groups.py --flip-sqlite   # 翻转注册表 sqlite_file 到组文件
    python scripts/split_sqlite_groups.py --prune-source  # 清源（回滚窗口终点，先确认 verify 全 OK）
"""
import argparse
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# (表, 过滤列)：全部按 doc_id 过滤；canonical_documents 本身即 doc 集合来源
_DOC_TABLES = [
    ("canonical_documents", "doc_id"),
    ("canonical_pages", "doc_id"),
    ("canonical_blocks", "doc_id"),
    ("canonical_chunks", "doc_id"),
    ("canonical_tables", "doc_id"),
    ("canonical_outlines", "doc_id"),
    ("canonical_citation_targets", "doc_id"),
    ("canonical_chunk_fts", "doc_id"),
    ("canonical_vectors", "doc_id"),
    ("doc_blocks", "doc_id"),
    ("document_segments", "doc_id"),
    ("doc_block_corrections", "doc_id"),
]


def _group_libraries() -> dict:
    """group_name → [library_id]（注册表读穿，active 行）。"""
    from docs_core import library_registry as registry

    groups: dict = {}
    for record in registry.list_libraries():
        groups.setdefault(record.group_name, []).append(record.library_id)
    return groups


def _group_target(group_name: str) -> Path:
    from docs_core import library_registry as registry

    rel = registry.GROUP_DEFAULTS.get(group_name, {}).get("sqlite_file")
    if not rel:
        raise ValueError(f"组 {group_name} 无 GROUP_DEFAULTS.sqlite_file")
    return registry.resolve_data_root() / rel


def _source_path() -> Path:
    from docs_core.paths import resolve_knowledge_index_db_path

    return resolve_knowledge_index_db_path()


def _ensure_target_schema(target: Path) -> None:
    """用两个 store 的 init_schema 在目标文件建全套表（与线上 schema 同源，不手抄 DDL）。"""
    from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeIndexStore
    from docs_core.step05_sqlite_fts.store.canonical_sql_store import CanonicalSQLiteStore

    CanonicalSQLiteStore(db_path=target)
    KnowledgeIndexStore(db_path=target)


def _existing_tables(conn: sqlite3.Connection, prefix: str = "") -> set:
    """源/目标实际存在的表集合（canonical_vectors 已在两端先后 DROP，缺表跳过不炸——
    2026-10-04 服务器搬迁实踩：服务器源库无 canonical_vectors）。"""
    rows = conn.execute(
        f"SELECT name FROM {prefix}sqlite_master WHERE type='table'"
    ).fetchall()
    return {str(r[0]) for r in rows}


def _doc_ids_of_group(src: sqlite3.Connection, library_ids: list) -> list:
    placeholders = ",".join("?" for _ in library_ids)
    rows = src.execute(
        f"SELECT doc_id FROM canonical_documents WHERE library_id IN ({placeholders})",
        library_ids,
    ).fetchall()
    return [str(r[0]) for r in rows]


def _migrate_group(group_name: str, library_ids: list, execute: bool) -> int:
    """搬一组；返回非零=失败。execute=False 时只打印应迁行数。"""
    src_path = _source_path()
    target = _group_target(group_name)
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src_tables = _existing_tables(src)
    doc_ids = _doc_ids_of_group(src, library_ids)
    print(f"[split-sqlite] {group_name}: {len(library_ids)} 库 / {len(doc_ids)} 文档 → {target}", flush=True)
    if not doc_ids:
        src.close()
        return 0

    if execute:
        _ensure_target_schema(target)
        dst = sqlite3.connect(str(target))
        dst.execute("PRAGMA journal_mode=WAL")
        dst.execute(f"ATTACH DATABASE '{src_path}' AS src")
        dst.execute("CREATE TEMP TABLE _move_docs (doc_id TEXT PRIMARY KEY)")
        dst.executemany("INSERT OR IGNORE INTO _move_docs VALUES (?)", [(d,) for d in doc_ids])
        try:
            for table, col in _DOC_TABLES:
                if table not in src_tables:
                    print(f"[split-sqlite]   {table}: 源无此表，跳过", flush=True)
                    continue
                # 显式列清单：源表经历史迁移列序可能与新建目标表不同（2026-10-03 实踩：
                # canonical_tables 的 page_bboxes_json 位置漂移，SELECT * 按位置拷贝整列错位），
                # 取源列 ∩ 目标列按名对齐
                src_cols = [r[1] for r in dst.execute(f"PRAGMA src.table_info({table})")]
                dst_cols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
                cols = [c for c in src_cols if c in dst_cols]
                col_list = ", ".join(cols)
                dst.execute(
                    f"DELETE FROM {table} WHERE {col} IN (SELECT doc_id FROM _move_docs)"
                )
                cursor = dst.execute(
                    f"INSERT INTO {table} ({col_list}) SELECT {col_list} FROM src.{table} "
                    f"WHERE {col} IN (SELECT doc_id FROM _move_docs)"
                )
                print(f"[split-sqlite]   {table}: {cursor.rowcount} 行", flush=True)
            dst.commit()
        except Exception:
            dst.rollback()
            raise
        finally:
            dst.close()
    else:
        for table, col in _DOC_TABLES:
            if table not in src_tables:
                continue
            placeholders = ",".join("?" for _ in [1])  # 用临时计数避免 999 变量上限
            count = 0
            batch = 500
            for start in range(0, len(doc_ids), batch):
                chunk = doc_ids[start : start + batch]
                ph = ",".join("?" for _ in chunk)
                count += src.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {col} IN ({ph})", chunk
                ).fetchone()[0]
            print(f"[split-sqlite]   {table}: {count} 行", flush=True)
    src.close()
    return 0


def _verify() -> int:
    """逐组逐表对账：行数相等 + **逐列长度和**相等（counts 抓不住整列错位——列置换下
    全列总长不变，只有 per-column 校验能抓住；2026-10-03 canonical_tables 错位实踩）。"""
    src_path = _source_path()
    src = sqlite3.connect(f"file:{src_path}?mode=ro", uri=True)
    src_tables = _existing_tables(src)
    ok = True
    for group_name, library_ids in sorted(_group_libraries().items()):
        target = _group_target(group_name)
        doc_ids = _doc_ids_of_group(src, library_ids)
        if not doc_ids:
            continue
        if not target.exists():
            print(f"[verify] MISMATCH {group_name}: 目标文件不存在 {target}", flush=True)
            ok = False
            continue
        dst = sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        for table, col in _DOC_TABLES:
            if table not in src_tables:
                continue
            try:
                src_cols = [r[1] for r in src.execute(f"PRAGMA table_info({table})")]
                dst_cols = [r[1] for r in dst.execute(f"PRAGMA table_info({table})")]
            except sqlite3.OperationalError:
                continue
            cols = [c for c in src_cols if c in dst_cols]
            expected = actual = 0
            col_diffs = []
            for start in range(0, len(doc_ids), 500):
                chunk = doc_ids[start : start + 500]
                ph = ",".join("?" for _ in chunk)
                where = f"WHERE {col} IN ({ph})"
                try:
                    expected += src.execute(
                        f"SELECT COUNT(*) FROM {table} {where}", chunk
                    ).fetchone()[0]
                    actual += dst.execute(
                        f"SELECT COUNT(*) FROM {table} {where}", chunk
                    ).fetchone()[0]
                except sqlite3.OperationalError:
                    pass  # 目标无此表（如空 canonical_vectors）按 0 计
                for c in cols:
                    expr = f"SUM(COALESCE(LENGTH(CAST({c} AS TEXT)), 0))"
                    try:
                        s = src.execute(f"SELECT {expr} FROM {table} {where}", chunk).fetchone()[0]
                        d = dst.execute(f"SELECT {expr} FROM {table} {where}", chunk).fetchone()[0]
                    except sqlite3.OperationalError:
                        continue
                    if (s or 0) != (d or 0):
                        col_diffs.append(c)
            if actual != expected or col_diffs:
                ok = False
                print(
                    f"[verify] MISMATCH {group_name}.{table}: 行数 目标{actual}/源{expected}"
                    + (f"；列和差异 {col_diffs}" if col_diffs else ""),
                    flush=True,
                )
        dst.close()
        print(f"[verify] {group_name} 各表对账完成", flush=True)
    src.close()
    print("[verify] " + ("全部 OK" if ok else "存在 MISMATCH"), flush=True)
    return 0 if ok else 1


def _flip_sqlite() -> int:
    """注册表 sqlite_file 翻转到组默认（原子切换点）；目标文件不存在拒翻。"""
    from docs_core import library_registry as registry

    flipped = 0
    for record in registry.list_libraries(include_retired=True):
        target_rel = registry.GROUP_DEFAULTS.get(record.group_name, {}).get("sqlite_file")
        if not target_rel or record.sqlite_file == target_rel:
            continue
        if not (registry.resolve_data_root() / target_rel).exists():
            print(f"[flip-sqlite] 拒翻 {record.library_id}: 目标文件不存在 {target_rel}", flush=True)
            continue
        registry.register_library(
            record.library_id,
            name=record.name,
            description=record.description,
            group_name=record.group_name,
            sqlite_file=target_rel,
            collection=record.collection,
            status=record.status,
        )
        flipped += 1
        print(f"[flip-sqlite] {record.library_id}: {record.sqlite_file} → {target_rel}", flush=True)
    print(f"[flip-sqlite] 完成：{flipped} 行翻转", flush=True)
    return 0


def _prune_source() -> int:
    """清源：删掉源单文件中已迁各组的行（回滚窗口终点）。"""
    src_path = _source_path()
    conn = sqlite3.connect(str(src_path))
    conn.execute("PRAGMA journal_mode=WAL")
    for group_name, library_ids in sorted(_group_libraries().items()):
        doc_ids = _doc_ids_of_group(conn, library_ids)
        if not doc_ids:
            continue
        conn.execute("CREATE TEMP TABLE IF NOT EXISTS _move_docs (doc_id TEXT PRIMARY KEY)")
        conn.execute("DELETE FROM _move_docs")
        conn.executemany("INSERT OR IGNORE INTO _move_docs VALUES (?)", [(d,) for d in doc_ids])
        for table, col in _DOC_TABLES:
            try:
                cursor = conn.execute(
                    f"DELETE FROM {table} WHERE {col} IN (SELECT doc_id FROM _move_docs)"
                )
            except sqlite3.OperationalError:
                continue
            print(f"[prune] {group_name}.{table}: -{cursor.rowcount} 行", flush=True)
    conn.commit()
    conn.close()
    print("[prune] 完成。建议随后 VACUUM 源文件回收空间", flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="sqlite 按组拆文件（DRY RUN 缺省）")
    parser.add_argument("--yes", action="store_true", help="执行搬迁（缺省 DRY RUN）")
    parser.add_argument("--verify", action="store_true", help="对账")
    parser.add_argument("--flip-sqlite", action="store_true", help="注册表 sqlite_file 翻转到组文件")
    parser.add_argument("--prune-source", action="store_true", help="清源（回滚窗口终点）")
    parser.add_argument("--group", default="", help="只处理指定组（缺省全部）")
    args = parser.parse_args()

    if args.verify:
        return _verify()
    if args.flip_sqlite:
        return _flip_sqlite()
    if args.prune_source:
        return _prune_source()

    groups = _group_libraries()
    if args.group:
        groups = {args.group: groups.get(args.group, [])}
    for group_name, library_ids in sorted(groups.items()):
        _migrate_group(group_name, library_ids, execute=args.yes)
    if not args.yes:
        print("[split-sqlite] DRY RUN：加 --yes 才真正搬迁", flush=True)
        return 2
    print("[split-sqlite] 搬迁完成。跑 --verify 对账，通过后 --flip-sqlite", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
