"""v2 语料包导入应用（P2-2）：预检 + 落位 + 图谱合并 + 快照 + 对账。

本模块与 ``corpus_package`` 的读取/闸函数同源；``corpus_package.apply_import`` 是惰性
wrapper，避免循环 import。

落位（2026-10-20 定版）：
- 每库独立桶：<目标组 libraries_dir>/<lib>/index.sqlite；
- files/ 按 data 根相对路径放回；包内文件根与目标组库根必须一致（否则拒绝，
  避免文件在 evals 根、注册表指向 knowledge 根的静默错位）；
- 图谱并入全局 graph.sqlite：连接 FK OFF + 单事务 + 固定顺序，事务内
  foreign_key_check 只放行「目标原有 ∪ 包内自带」悬空，新增违例回滚；
- qdrant 快照直接 upload 成 <lib_id> collection；
- 全部写完后再写 registry，最后逐表对账。
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import sqlite3
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from . import library_registry
from .corpus_package import (
    Bundle,
    BundleError,
    BundleLibrary,
    check_conflict_gate,
    check_embed_gate,
    check_package_files,
    count_points_filtered,
    embed_model_from_env,
    open_bundle,
)
from .step05_sqlite_fts.store.sqlite_utils import create_connection

logger = logging.getLogger(__name__)

GRAPH_ORDER = (
    "graph_entities",
    "graph_principles",
    "graph_examples",
    "graph_warnings",
    "graph_frameworks",
    "principle_entities",
    "example_entities",
    "warning_entities",
    "graph_entity_deletions",
    "graph_relations",
)

# 包内 library_id 直接决定目标目录/collection 名；现网有 lib-DredgeAI-a5e1 这类大写。
_LIBRARY_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")

_JUNCTION_KEYS = {
    "principle_entities": ("principle_id", "entity_id"),
    "example_entities": ("example_id", "entity_id"),
    "warning_entities": ("warning_id", "entity_id"),
}


class ImportApplyError(BundleError):
    """导入应用阶段失败（已完成步骤随异常文本返回）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_libraries_dir(group_name: str) -> str:
    if group_name in library_registry.GROUP_DEFAULTS:
        return library_registry.GROUP_DEFAULTS[group_name]["libraries_dir"]
    return "knowledge/libraries"


def _group_display(group_name: str, display_name: str = "") -> str:
    return (display_name or "").strip() or group_name


def _ensure_target_group(reg_path: Path, group_name: str, display_name: str = "") -> None:
    library_registry.ensure_schema(reg_path)
    if group_name in library_registry.GROUP_DEFAULTS:
        return
    if not library_registry.GROUP_NAME_RE.match(group_name or ""):
        raise BundleError(
            f"非法目标组名: {group_name!r}（须小写字母开头，2–32 位小写字母/数字/_/-）")
    now = _now()
    conn = create_connection(reg_path)
    try:
        conn.execute(
            "INSERT OR IGNORE INTO library_groups (group_name, display_name, created_at, updated_at) "
            "VALUES (?,?,?,?)",
            (group_name, _group_display(group_name, display_name), now, now),
        )
        conn.commit()
    finally:
        conn.close()


def _validate_library_id(lib_id: str) -> None:
    if not _LIBRARY_ID_RE.match(lib_id or ""):
        raise BundleError(
            f"非法 library_id: {lib_id!r}（须以字母/数字开头，仅字母数字/下划线/连字符，1–64 位）")


def _source_library_root(lb: BundleLibrary) -> str:
    """从 files/ 条目推断源库根（如 knowledge/libraries/lib-a）。"""
    roots = set()
    for arc in lb.files_index:
        if not arc.startswith("files/"):
            continue
        rel = arc[6:]
        if "/documents/" not in rel:
            raise BundleError(f"[{lb.library_id}] files 条目不在 documents/ 下: {arc}")
        roots.add(rel.split("/documents/")[0])
    if not roots:
        return ""
    if len(roots) > 1:
        raise BundleError(f"[{lb.library_id}] files 条目跨多个库根: {sorted(roots)}")
    root = roots.pop()
    if not root.endswith("/" + lb.library_id):
        raise BundleError(f"[{lb.library_id}] files 库根不以 library_id 结尾: {root}")
    return root


def _safe_rel(arc: str) -> str:
    rel = arc[6:] if arc.startswith("files/") else arc
    if not rel or rel.startswith("/") or "\\" in rel:
        raise BundleError(f"非法包内路径: {arc}")
    parts = rel.split("/")
    if any(p in ("", ".", "..") for p in parts):
        raise BundleError(f"非法包内路径: {arc}")
    return rel


def _target_index_rel(data_root: Path, group_name: str, lib_id: str) -> str:
    return (_target_libraries_dir(group_name).rstrip("/") + f"/{lib_id}/index.sqlite")


def _target_index_path(data_root: Path, group_name: str, lib_id: str) -> Path:
    return data_root / _target_index_rel(data_root, group_name, lib_id)


def _read_json_entry(lb: BundleLibrary, arc: str) -> Dict[str, Any]:
    try:
        with lb.open_entry(arc) as fh:
            return json.loads(fh.read().decode("utf-8"))
    except KeyError as exc:
        raise BundleError(f"[{lb.library_id}] 缺条目: {arc}") from exc
    except ValueError as exc:
        raise BundleError(f"[{lb.library_id}] {arc} JSON 解析失败: {exc}") from exc


def _copy_entry(lb: BundleLibrary, arc: str, dst: Path) -> None:
    if dst.exists():
        raise BundleError(f"[{lb.library_id}] 目标已存在，拒绝覆盖: {dst}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with lb.open_entry(arc) as src, dst.open("wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)


def _extract_entry(lb: BundleLibrary, arc: str, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with lb.open_entry(arc) as src, dst.open("wb") as out:
        shutil.copyfileobj(src, out, 1 << 20)


def _registry_snapshot(reg_path: Path) -> tuple[List[dict], List[dict]]:
    if not reg_path.exists():
        return [], []
    conn = create_connection(reg_path)
    conn.row_factory = sqlite3.Row
    try:
        libs = [dict(r) for r in conn.execute("SELECT * FROM library_registry")]
        has_groups = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='library_groups'"
        ).fetchone()
        groups = [dict(r) for r in conn.execute("SELECT * FROM library_groups")] if has_groups else []
        return libs, groups
    finally:
        conn.close()


def _meta_rows(meta_path: Path, lib_ids: Sequence[str], table: str, key: str) -> List[dict]:
    if not meta_path.exists() or not lib_ids:
        return []
    conn = create_connection(meta_path)
    conn.row_factory = sqlite3.Row
    try:
        marks = ",".join("?" * len(lib_ids))
        return [dict(r) for r in conn.execute(
            f'SELECT * FROM "{table}" WHERE "{key}" IN ({marks})', list(lib_ids))]
    finally:
        conn.close()


def _rows_for_lib(meta: Dict[str, Any], lib_id: str) -> Dict[str, List[dict]]:
    return {
        "nodes": [r for r in meta.get("nodes", []) if str(r.get("library_id")) == lib_id],
        "tree_nodes": [r for r in meta.get("tree_nodes", []) if str(r.get("scope_id")) == lib_id],
        "libraries": [r for r in meta.get("libraries", []) if str(r.get("id")) == lib_id],
    }


def _insert_rows(conn: sqlite3.Connection, table: str, rows: Sequence[dict]) -> int:
    if not rows:
        return 0
    existing = {r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')}
    if not existing:
        raise BundleError(f"目标库缺表: {table}")
    columns = [c for c in rows[0] if c in existing]
    if not columns:
        raise BundleError(f"目标表 {table} 无可写列")
    marks = ",".join("?" * len(columns))
    col_list = ",".join(f'"{c}"' for c in columns)
    values = [[row.get(c) for c in columns] for row in rows]
    conn.executemany(f'INSERT INTO "{table}" ({col_list}) VALUES ({marks})', values)
    return len(values)


def _fk_signatures(conn: sqlite3.Connection) -> set:
    """PRAGMA foreign_key_check 的稳定签名（rowid → 主键）。"""
    sigs = set()
    for table, rowid, _parent, _fkid in conn.execute("PRAGMA foreign_key_check"):
        try:
            if table == "graph_relations":
                key = conn.execute(
                    "SELECT relation_id FROM graph_relations WHERE rowid=?", (rowid,)
                ).fetchone()
                sigs.add(("graph_relations", str(key[0]) if key else f"rowid:{rowid}"))
            elif table in _JUNCTION_KEYS:
                cols = _JUNCTION_KEYS[table]
                key = conn.execute(
                    f'SELECT {",".join(cols)} FROM "{table}" WHERE rowid=?', (rowid,)
                ).fetchone()
                sigs.add((table, *(str(x) for x in key)) if key else (table, f"rowid:{rowid}"))
            else:
                sigs.add((table, f"rowid:{rowid}"))
        except sqlite3.Error:
            sigs.add((table, f"rowid:{rowid}"))
    return sigs


def _merge_graph(package_graph: Path, target_graph: Path) -> Dict[str, int]:
    import gc

    from .step07_graph.graph_store import GraphStore

    if not target_graph.exists():
        GraphStore(str(target_graph)).close()
        gc.collect()  # GraphStore 初始化连接进引用循环；Windows 不 gc 会锁住新库文件
    src = sqlite3.connect(str(package_graph))
    dst = sqlite3.connect(str(target_graph))
    try:
        dst.execute("PRAGMA foreign_keys=OFF")
        dst.execute("BEGIN IMMEDIATE")
        before = _fk_signatures(dst)
        package_dangling = _fk_signatures(src)
        src_tables = {r[0] for r in src.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        counts: Dict[str, int] = {}
        for table in GRAPH_ORDER:
            if table not in src_tables:
                continue
            src_cols = [r[1] for r in src.execute(f'PRAGMA table_info("{table}")')]
            dst_cols = {r[1] for r in dst.execute(f'PRAGMA table_info("{table}")')}
            cols = [c for c in src_cols if c in dst_cols]
            if not cols:
                continue
            col_sql = ",".join(f'"{c}"' for c in cols)
            rows = src.execute(f'SELECT {col_sql} FROM "{table}"').fetchall()
            if rows:
                marks = ",".join("?" * len(cols))
                dst.executemany(
                    f'INSERT OR IGNORE INTO "{table}" ({col_sql}) VALUES ({marks})',
                    rows,
                )
            counts[table] = len(rows)
        after = _fk_signatures(dst)
        new = after - before - package_dangling
        if new:
            dst.rollback()
            sample = sorted(new)[0]
            raise ImportApplyError(
                f"图谱合并引入 {len(new)} 条新悬空（样例 {sample}）；已回滚")
        dst.commit()
        return counts
    except Exception:
        try:
            dst.rollback()
        except sqlite3.Error:
            pass
        raise
    finally:
        src.close()
        dst.close()


def _list_qdrant_collections(qdrant_url: Optional[str]) -> Optional[set]:
    from urllib import request as urlrequest

    base = (qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")).rstrip("/")
    try:
        with urlrequest.urlopen(f"{base}/collections", timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {str(c.get("name")) for c in data.get("result", {}).get("collections", [])}
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取 qdrant collections 失败: %s", exc)
        return None


def _upload_snapshot(lib_id: str, snapshot: Path, qdrant_url: Optional[str]) -> None:
    import httpx

    base = (qdrant_url or os.getenv("QDRANT_URL", "http://localhost:6333")).rstrip("/")
    url = f"{base}/collections/{lib_id}/snapshots/upload?priority=snapshot"
    with snapshot.open("rb") as fh:
        with httpx.Client(timeout=600, trust_env=False) as client:
            resp = client.post(
                url,
                files={"snapshot": (snapshot.name, fh, "application/octet-stream")},
            )
    if resp.status_code >= 400:
        raise ImportApplyError(
            f"qdrant 快照恢复失败: {lib_id} HTTP {resp.status_code} {resp.text[:300]}")


def _insert_meta(meta_path: Path, meta: Dict[str, Any], lib_id: str) -> None:
    rows = _rows_for_lib(meta, lib_id)
    if not any(rows.values()):
        return
    conn = create_connection(meta_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        _insert_rows(conn, "nodes", rows["nodes"])
        _insert_rows(conn, "tree_node", rows["tree_nodes"])
        _insert_rows(conn, "libraries", rows["libraries"])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _insert_registry(
    reg_path: Path,
    group_name: str,
    lib_id: str,
    source_row: dict,
    display_name: str,
    index_rel: str,
) -> None:
    _ensure_target_group(reg_path, group_name, display_name)
    now = _now()
    conn = create_connection(reg_path)
    try:
        conn.execute(
            "INSERT INTO library_registry "
            "(library_id, name, description, group_name, sqlite_file, collection, status, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                lib_id,
                str(source_row.get("name") or lib_id),
                str(source_row.get("description") or ""),
                group_name,
                index_rel,
                lib_id,
                library_registry.STATUS_ACTIVE,
                now,
                now,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def _verify_library(
    lib_id: str,
    index_path: Path,
    collection: str,
    counts: Dict[str, Any],
    qdrant_url: Optional[str],
    with_vectors: bool,
    graph_path: Path,
) -> None:
    if not index_path.exists():
        raise ImportApplyError(f"[{lib_id}] 缺 index.sqlite")
    conn = create_connection(index_path)
    try:
        docs = conn.execute("SELECT COUNT(*) FROM canonical_documents").fetchone()[0]
        chunks = conn.execute("SELECT COUNT(*) FROM canonical_chunks").fetchone()[0]
    finally:
        conn.close()
    expect_docs = int(counts.get("docs") or 0)
    expect_chunks = int(counts.get("chunks") or 0)
    if int(docs) != expect_docs:
        raise ImportApplyError(f"[{lib_id}] docs 对账失败: {docs} != {expect_docs}")
    if int(chunks) != expect_chunks:
        raise ImportApplyError(f"[{lib_id}] chunks 对账失败: {chunks} != {expect_chunks}")
    graph_tables = counts.get("graph_tables") or {}
    if graph_tables:
        if not graph_path.exists():
            raise ImportApplyError(f"[{lib_id}] 缺 graph.sqlite")
        g = sqlite3.connect(str(graph_path))
        try:
            for table in ("graph_relations", "graph_principles",
                          "graph_examples", "graph_warnings", "graph_frameworks",
                          "graph_entity_deletions"):
                expected = int(graph_tables.get(table) or 0)
                actual = g.execute(
                    f'SELECT COUNT(*) FROM "{table}" WHERE library_id = ?', (lib_id,)
                ).fetchone()[0]
                if int(actual) != expected:
                    raise ImportApplyError(
                        f"[{lib_id}] graph.{table} 对账失败: {actual} != {expected}")
        finally:
            g.close()
    if with_vectors:
        got = count_points_filtered(collection, lib_id, qdrant_url)
        expect = int(counts.get("vectors") or 0)
        if got != expect:
            raise ImportApplyError(f"[{lib_id}] vectors 对账失败: {got} != {expect}")


def import_bundle(
    package_path: str | Path,
    *,
    data_root: Optional[Path] = None,
    group_name: str = "",
    group_display_name: str = "",
    libraries: Optional[Sequence[str]] = None,
    apply: bool = False,
    with_vectors: bool = True,
    qdrant_url: Optional[str] = None,
) -> Dict[str, Any]:
    """预检（apply=False）或应用（apply=True）v2 包。"""
    data_root = Path(data_root).resolve() if data_root else library_registry.resolve_data_root()
    reg_path = data_root / library_registry.REGISTRY_DB_NAME
    meta_path = data_root / "knowledge" / "knowledge_meta.sqlite"
    scratch = Path(tempfile.mkdtemp(prefix="kb-import-"))
    try:
        with open_bundle(package_path) as bundle:
            selected = [lb for lb in bundle.libraries
                        if not libraries or lb.library_id in set(libraries)]
            if libraries:
                missing = sorted(set(libraries) - {lb.library_id for lb in selected})
                if missing:
                    raise BundleError(f"包内缺库: {missing}")
            if not selected:
                raise BundleError("没有选中任何库")
            check_embed_gate(bundle.manifest, embed_model_from_env())
            check_package_files(bundle)

            target_libs, _groups = _registry_snapshot(reg_path)
            target_lib_ids = {r["library_id"] for r in target_libs}
            target_collections = {r["collection"] for r in target_libs}
            qdrant_cols = _list_qdrant_collections(qdrant_url) if with_vectors else set()
            if qdrant_cols is None:
                if with_vectors:
                    raise BundleError("无法读取目标 qdrant collections，拒绝在未知状态下导入向量")
            else:
                target_collections |= qdrant_cols

            plans: List[Dict[str, Any]] = []
            all_node_ids: List[str] = []
            package_entities: List[dict] = []
            for lb in selected:
                _validate_library_id(lb.library_id)
                target_group = group_name or lb.group_name or library_registry.DEFAULT_GROUP
                src_root = _source_library_root(lb)
                target_root = (_target_libraries_dir(target_group).rstrip("/") + f"/{lb.library_id}")
                if src_root and src_root != target_root:
                    raise BundleError(
                        f"[{lb.library_id}] 包文件根 {src_root} 与目标组库根 {target_root} 不一致；"
                        f"请选择匹配的目标组（evals 包用 evals 组），或先改写包内路径")
                index_path = data_root / _target_index_rel(data_root, target_group, lb.library_id)
                if index_path.exists():
                    raise BundleError(f"[{lb.library_id}] 目标已有 index.sqlite: {index_path}")
                files = []
                for arc in lb.files_index:
                    if not arc.startswith("files/"):
                        continue
                    rel = _safe_rel(arc)
                    if src_root and not rel.startswith(src_root + "/"):
                        raise BundleError(f"[{lb.library_id}] files 越出库根: {arc}")
                    files.append((arc, rel))
                if "index/index.sqlite" not in lb.files_index:
                    raise BundleError(f"[{lb.library_id}] 缺 index/index.sqlite")
                meta = _read_json_entry(lb, "meta/rows.json")
                rows = _rows_for_lib(meta, lb.library_id)
                all_node_ids.extend(str(r.get("id")) for r in rows["nodes"] if r.get("id"))
                if "graph/graph.sqlite" in lb.files_index:
                    graph_path = scratch / lb.library_id / "graph.sqlite"
                    _extract_entry(lb, "graph/graph.sqlite", graph_path)
                    conn = sqlite3.connect(str(graph_path))
                    try:
                        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='graph_entities'").fetchone():
                            package_entities.extend(
                                {"entity_id": r[0], "name": r[1], "library_id": r[2]}
                                for r in conn.execute(
                                    "SELECT entity_id, name, library_id FROM graph_entities"))
                    finally:
                        conn.close()
                plans.append({
                    "library_id": lb.library_id,
                    "name": lb.name,
                    "group_name": target_group,
                    "source_root": src_root,
                    "target_root": target_root,
                    "index_path": index_path,
                    "index_rel": _target_index_rel(data_root, target_group, lb.library_id),
                    "files": files,
                    "meta": meta,
                    "counts": lb.manifest.get("counts", {}),
                    "manifest": lb.manifest,
                    "lib": lb,
                })

            # 目标 node id 全表读一次（目标 node 通常 <10 万；冲突闸只做交集）
            target_node_ids: set = set()
            if meta_path.exists():
                conn = create_connection(meta_path)
                try:
                    target_node_ids = {str(r[0]) for r in conn.execute("SELECT id FROM nodes")}
                finally:
                    conn.close()
            target_entities: Dict[tuple, str] = {}
            graph_target = data_root / "knowledge" / "graph.sqlite"
            if graph_target.exists():
                conn = sqlite3.connect(str(graph_target))
                try:
                    if conn.execute("SELECT 1 FROM sqlite_master WHERE name='graph_entities'").fetchone():
                        target_entities = {
                            (str(r[1]), str(r[2])): str(r[0])
                            for r in conn.execute("SELECT entity_id, name, library_id FROM graph_entities")
                        }
                finally:
                    conn.close()

            gate = check_conflict_gate(
                package_libs=[{"library_id": p["library_id"]} for p in plans],
                package_node_ids=all_node_ids,
                target_library_ids=target_lib_ids,
                target_node_ids=target_node_ids,
                target_collections=target_collections,
                existing_index_files=[p["library_id"] for p in plans if p["index_path"].exists()],
                package_entities=package_entities,
                target_entities=target_entities,
            )
            if gate["clashes"]:
                raise BundleError("冲突闸拒绝: " + "；".join(gate["clashes"][:10]))
            if gate["warnings"]:
                raise BundleError("闭包实体冲突，首版阻断: " + "；".join(gate["warnings"][:5]))

            if not apply:
                return {
                    "mode": "dry-run",
                    "package": str(package_path),
                    "libraries": [{
                        "library_id": p["library_id"],
                        "name": p["name"],
                        "group_name": p["group_name"],
                        "collection": p["library_id"],
                        "index_path": str(p["index_path"]),
                        "files": len(p["files"]),
                        "counts": p["counts"],
                    } for p in plans],
                }

            completed: List[str] = []
            try:
                for p in plans:
                    lb = p["lib"]
                    lib_id = p["library_id"]
                    completed.append(f"{lib_id}:files")
                    for arc, rel in p["files"]:
                        _copy_entry(lb, arc, data_root / rel)
                    completed.append(f"{lib_id}:index")
                    _copy_entry(lb, "index/index.sqlite", p["index_path"])
                    completed.append(f"{lib_id}:graph")
                    if "graph/graph.sqlite" in lb.files_index:
                        _merge_graph(scratch / lib_id / "graph.sqlite",
                                     data_root / "knowledge" / "graph.sqlite")
                    completed.append(f"{lib_id}:meta")
                    _insert_meta(meta_path, p["meta"], lib_id)
                    completed.append(f"{lib_id}:vectors")
                    if with_vectors and "qdrant/vectors.snapshot" in lb.files_index:
                        snap = scratch / lib_id / "vectors.snapshot"
                        _extract_entry(lb, "qdrant/vectors.snapshot", snap)
                        _upload_snapshot(lib_id, snap, qdrant_url)
                    completed.append(f"{lib_id}:registry")
                    source_row = (_read_json_entry(lb, "registry/rows.json").get("libraries") or [{}])[0]
                    _insert_registry(
                        reg_path, p["group_name"], lib_id, source_row,
                        group_display_name, p["index_rel"],
                    )
                    completed.append(f"{lib_id}:verify")
                    _verify_library(lib_id, p["index_path"], lib_id, p["counts"],
                                    qdrant_url, with_vectors,
                                    data_root / "knowledge" / "graph.sqlite")
            except Exception as exc:
                raise ImportApplyError(
                    f"导入失败（已完成: {completed[-8:]}）: {exc}") from exc
            return {
                "mode": "applied",
                "package": str(package_path),
                "libraries": [p["library_id"] for p in plans],
                "completed": completed,
            }
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
