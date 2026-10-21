"""v2 导入残留清理 CLI：孤儿暂存包 + 半成品库（registry 无行）。

场景（P3-4 kill 演练）：apply 在 files/index/graph/meta 之后、registry 之前被强杀，
进程内任务表随进程消失 → ``DELETE /api/knowledge/imports/<task_id>`` 只能 404：
- 暂存包留在 ``<data 根>/scratch/imports/<task_id>/package.zip``；
- 半成品库目录/index/meta/图谱行已落盘，但 registry 没有该行；
- 列表接口会把它当库显示（group/collection 为空），再次导入又被 index.sqlite 冲突闸拦住。

本脚本只做两件事，默认 dry-run 只打印：
1. ``--scratch``：清理 ``scratch/imports/*`` 孤儿暂存目录（进程内任务表不持久，重启后全是孤儿）；
2. 清理 **registry 无行** 的半成品库：目录 + meta 行 + 解析台账 + 图谱行 + 同名 qdrant 集合。

安全边界：
- registry 有任何行（含 retired）的库一律不动；
- ``--scratch`` 建议在 docs-api 停止或确认无导入进行时执行（无法探测进程内活跃任务）；
- 默认 dry-run，必须 ``--apply`` 才删；``--library`` 可只清指定库。

用法::

    python scripts/kb_corpus_import_cleanup.py                 # 只列出残留
    python scripts/kb_corpus_import_cleanup.py --apply --scratch
    python scripts/kb_corpus_import_cleanup.py --apply --library default
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "services" / "docs-core" / "src"))

from docs_core import library_registry  # noqa: E402

LIBRARY_DIR_ROOTS = (
    ("knowledge", "libraries"),
    ("evals", "corpora", "libraries"),
)


def _connect(path: Path) -> Optional[sqlite3.Connection]:
    if not path.exists():
        return None
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)


def registry_ids(data_root: Path) -> set:
    conn = _connect(data_root / "registry.sqlite")
    if conn is None:
        return set()
    try:
        return {str(r[0]) for r in conn.execute("SELECT library_id FROM library_registry")}
    except sqlite3.Error:
        return set()
    finally:
        conn.close()


def registry_collections(data_root: Path) -> set:
    conn = _connect(data_root / "registry.sqlite")
    if conn is None:
        return set()
    try:
        return {str(r[0]) for r in conn.execute("SELECT collection FROM library_registry")}
    except sqlite3.Error:
        return set()
    finally:
        conn.close()


def orphan_scratch(data_root: Path) -> List[Path]:
    root = data_root / "scratch" / "imports"
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.is_dir())


def _library_dirs(data_root: Path, library_id: str) -> List[Path]:
    return [data_root.joinpath(*parts, library_id) for parts in LIBRARY_DIR_ROOTS
            if data_root.joinpath(*parts, library_id).is_dir()]


def _meta_rows(data_root: Path, library_id: str) -> Dict[str, int]:
    """meta 中该库残留行数（nodes/tree_node/libraries）。"""
    meta = data_root / "knowledge" / "knowledge_meta.sqlite"
    conn = _connect(meta)
    if conn is None:
        return {}
    counts: Dict[str, int] = {}
    try:
        for table, column in (("nodes", "library_id"), ("tree_node", "scope_id"), ("libraries", "id")):
            try:
                counts[table] = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE "{column}"=?', (library_id,)
                ).fetchone()[0])
            except sqlite3.Error:
                counts[table] = 0
    finally:
        conn.close()
    return counts


def _graph_rows(data_root: Path, library_id: str) -> Dict[str, int]:
    conn = _connect(data_root / "knowledge" / "graph.sqlite")
    if conn is None:
        return {}
    counts: Dict[str, int] = {}
    try:
        for table in ("graph_entities", "graph_relations"):
            try:
                counts[table] = int(conn.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE library_id=?', (library_id,)
                ).fetchone()[0])
            except sqlite3.Error:
                counts[table] = 0
    finally:
        conn.close()
    return counts


def _parse_record_count(data_root: Path, library_id: str) -> int:
    conn = _connect(data_root / "knowledge" / "parse_records.sqlite")
    if conn is None:
        return 0
    try:
        return int(conn.execute(
            "SELECT COUNT(*) FROM parse_records WHERE library_id=?", (library_id,)
        ).fetchone()[0])
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _qdrant_collection_exists(library_id: str, qdrant_url: str) -> bool:
    try:
        with urllib.request.urlopen(f"{qdrant_url}/collections/{library_id}", timeout=5) as resp:
            return resp.status == 200
    except urllib.error.HTTPError as exc:
        return exc.code != 404
    except Exception:  # noqa: BLE001 — qdrant 不可达时只跳过集合检查
        return False


def find_partial_libraries(data_root: Path, known: set) -> List[str]:
    """registry 无行、但有目录或 meta 行的库 id。"""
    candidates: set = set()
    for parts in LIBRARY_DIR_ROOTS:
        root = data_root.joinpath(*parts)
        if root.is_dir():
            for child in root.iterdir():
                if child.is_dir() and child.name not in known:
                    candidates.add(child.name)
    meta = data_root / "knowledge" / "knowledge_meta.sqlite"
    conn = _connect(meta)
    if conn is not None:
        try:
            for row in conn.execute("SELECT id FROM libraries"):
                if str(row[0]) not in known:
                    candidates.add(str(row[0]))
            for row in conn.execute("SELECT DISTINCT library_id FROM nodes WHERE deleted=0"):
                if str(row[0]) and str(row[0]) not in known:
                    candidates.add(str(row[0]))
        except sqlite3.Error:
            pass
        finally:
            conn.close()
    return sorted(candidates)


def _delete_meta_rows(data_root: Path, library_id: str) -> Dict[str, int]:
    meta = data_root / "knowledge" / "knowledge_meta.sqlite"
    if not meta.exists():
        return {}
    conn = sqlite3.connect(str(meta))
    deleted: Dict[str, int] = {}
    try:
        with conn:
            for table, column in (("nodes", "library_id"), ("tree_node", "scope_id"), ("libraries", "id")):
                try:
                    cur = conn.execute(f'DELETE FROM "{table}" WHERE "{column}"=?', (library_id,))
                    deleted[table] = cur.rowcount
                except sqlite3.Error:
                    deleted[table] = 0
    finally:
        conn.close()
    return deleted


def _delete_parse_records(data_root: Path, library_id: str) -> int:
    db = data_root / "knowledge" / "parse_records.sqlite"
    if not db.exists():
        return 0
    conn = sqlite3.connect(str(db))
    try:
        with conn:
            return conn.execute("DELETE FROM parse_records WHERE library_id=?", (library_id,)).rowcount
    except sqlite3.Error:
        return 0
    finally:
        conn.close()


def _delete_graph_rows(data_root: Path, library_id: str) -> Dict[str, int]:
    from docs_core.step07_graph.graph_store import GraphStore

    graph = data_root / "knowledge" / "graph.sqlite"
    if not graph.exists():
        return {}
    store = GraphStore(str(graph))
    try:
        return store.delete_library(library_id)
    finally:
        try:
            store.close()
        except Exception:  # noqa: BLE001
            pass


def _delete_qdrant_collection(library_id: str, qdrant_url: str) -> bool:
    req = urllib.request.Request(f"{qdrant_url}/collections/{library_id}", method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception:  # noqa: BLE001
        return False


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="真正删除（默认 dry-run 只打印）")
    parser.add_argument("--scratch", action="store_true", help="清理 scratch/imports/* 孤儿暂存目录")
    parser.add_argument("--library", action="append", default=[],
                        help="只清指定半成品库 id（可多次；默认清全部 registry 无行的候选）")
    parser.add_argument("--qdrant-url", default=os.getenv("QDRANT_URL", "http://localhost:6333"),
                        help="用于检查/删除同名 qdrant 集合（默认取 QDRANT_URL）")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    data_root = library_registry.resolve_data_root()
    known = registry_ids(data_root)
    known_collections = registry_collections(data_root)
    report: Dict[str, object] = {"data_root": str(data_root), "mode": "apply" if args.apply else "dry-run"}

    staging = orphan_scratch(data_root) if args.scratch else []
    report["orphan_staging"] = [
        {"path": str(p), "bytes": sum(f.stat().st_size for f in p.rglob("*") if f.is_file())}
        for p in staging
    ]

    candidates = find_partial_libraries(data_root, known)
    if args.library:
        unknown = sorted(set(args.library) - set(candidates))
        if unknown:
            print(f"拒绝：指定库不是半成品（registry 有行或目标不存在）: {unknown}", file=sys.stderr)
            return 2
        candidates = sorted(set(args.library))
    partials = []
    for lib_id in candidates:
        dirs = _library_dirs(data_root, lib_id)
        item = {
            "library_id": lib_id,
            "dirs": [str(d) for d in dirs],
            "meta": _meta_rows(data_root, lib_id),
            "graph": _graph_rows(data_root, lib_id),
            "parse_records": _parse_record_count(data_root, lib_id),
            "qdrant_collection": (lib_id not in known_collections
                                  and _qdrant_collection_exists(lib_id, args.qdrant_url)),
        }
        partials.append(item)
    report["partial_libraries"] = partials

    if not args.apply:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        print("\n确认后加 --apply；建议先停 docs-api，确认没有正在跑的上传/应用。")
        return 0

    removed = []
    for path in staging:
        shutil.rmtree(path, ignore_errors=True)
        removed.append(str(path))
    for item in partials:
        lib_id = str(item["library_id"])
        _delete_meta_rows(data_root, lib_id)
        _delete_parse_records(data_root, lib_id)
        _delete_graph_rows(data_root, lib_id)
        for path_str in item["dirs"]:
            shutil.rmtree(path_str, ignore_errors=True)
        if item["qdrant_collection"]:
            _delete_qdrant_collection(lib_id, args.qdrant_url)
        removed.append(f"library:{lib_id}")

    print(json.dumps({"data_root": str(data_root), "removed": removed}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
