"""中性语料包导入（engine-neutral v2 → legacy 或 pg，经存储抽象写入目标档位）。

目标档位由进程 ``KB_STACK`` 决定（pg=PostgreSQL+pgvector；legacy=SQLite+Qdrant），
导入器对两后端走同一套 store API / 适配 SQL：

- canonical：逐文档从 jsonl.gz 重建 ``CanonicalDocument`` → ``canonical_store.save_document``
  （clear+insert+FTS 回填的既有幂等写路径，两后端同实现）；
- index（doc_blocks/document_segments）：行级 INSERT OR REPLACE（``id`` 剥离自增，
  ``block_uid`` 唯一索引做幂等锚点；PG 侧导入后同步序列）；
- meta（nodes/tree_node/libraries）：行级 INSERT OR REPLACE；
- 向量：parquet → ``VectorRecord`` → ``VectorStore.upsert_records``（Qdrant API / pgvector，
  **不经快照、不经 reembed**，同模型零重嵌）；
- registry：``register_library``（collection=library_id 独立桶，与 legacy 导入器同语义）；
- 台账：按 nodes 重建 parse_records 行（legacy 导入器同口径）；
- 对账：manifest counts vs 目标逐表 COUNT + 向量点数。

冲突闸：目标已存在同 ``library_id``（非 retired）→ 拒绝；重导请先按库删除（幂等冒烟口径）。
包内缺 graph/台账（与 legacy 包同口径）：图按需重建、台账从空开始。
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from . import library_registry
from .docs_service import get_docs_service
from .step06_vectors.vector_store import VectorRecord

logger = logging.getLogger(__name__)

READ_CHUNK = 1 << 20
_UPSERT_BATCH = 256


class NeutralImportError(ValueError):
    """中性包导入失败（含预检与对账）。"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_libraries_dir(group_name: str) -> str:
    if group_name in library_registry.GROUP_DEFAULTS:
        return library_registry.GROUP_DEFAULTS[group_name]["libraries_dir"]
    return "knowledge/libraries"


# ---- 包读取 -----------------------------------------------------------------


def _read_manifest(zf: zipfile.ZipFile, arcname: str) -> Dict[str, Any]:
    try:
        return json.loads(zf.read(arcname).decode("utf-8"))
    except KeyError as exc:
        raise NeutralImportError(f"缺条目: {arcname}") from exc
    except ValueError as exc:
        raise NeutralImportError(f"{arcname} JSON 解析失败: {exc}") from exc


def _sha256_entry(zf: zipfile.ZipFile, arcname: str) -> str:
    h = hashlib.sha256()
    with zf.open(arcname) as fh:
        for chunk in iter(lambda: fh.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


class _LibPackage:
    """内层库小包的读取视图（manifest + jsonl 行 + parquet + files 流）。"""

    def __init__(self, zf: zipfile.ZipFile, manifest: Dict[str, Any]) -> None:
        self._zf = zf
        self.manifest = manifest
        self.library_id = str(manifest.get("library_id") or "")
        self.counts = dict(manifest.get("counts") or {})
        self.files_index: Dict[str, Dict[str, Any]] = dict(manifest.get("files") or {})

    def jsonl_rows(self, arcname: str) -> Iterator[Dict[str, Any]]:
        with self._zf.open(arcname) as fh:
            import gzip

            with gzip.GzipFile(fileobj=fh, mode="rb") as gz:
                for line in gz:
                    line = line.strip()
                    if line:
                        yield json.loads(line.decode("utf-8"))

    def open_entry(self, arcname: str):
        return self._zf.open(arcname)

    def verify_entry_sha256(self, arcname: str) -> None:
        expected = self.files_index.get(arcname, {}).get("sha256")
        if expected and _sha256_entry(self._zf, arcname) != expected:
            raise NeutralImportError(f"[{self.library_id}] sha256 不符: {arcname}")


def _open_bundle(package_path: str | Path) -> Tuple[zipfile.ZipFile, Dict[str, Any], List[_LibPackage]]:
    path = Path(package_path)
    if not path.exists():
        raise NeutralImportError(f"包不存在: {path}")
    outer = zipfile.ZipFile(path)
    try:
        manifest = _read_manifest(outer, "manifest.json")
    except Exception:
        outer.close()
        raise
    if str(manifest.get("format") or "") != "neutral-v2":
        outer.close()
        raise NeutralImportError(
            "不是中性 v2 包（format=neutral-v2）；legacy 快照包请走 kb_corpus_import 旧通道")
    libs: List[_LibPackage] = []
    for entry in manifest.get("libraries") or []:
        arc = str(entry.get("entry") or "")
        inner = zipfile.ZipFile(outer.open(arc))
        try:
            lib_manifest = _read_manifest(inner, "manifest.json")
        except Exception:
            inner.close()
            outer.close()
            raise
        libs.append(_LibPackage(inner, lib_manifest))
    return outer, manifest, libs


# ---- 行写入（目标档位经适配器同 SQL）----------------------------------------


def _table_columns(conn: Any, table: str) -> List[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row[1] for row in rows]


def _upsert_rows(conn: Any, table: str, rows: Sequence[Dict[str, Any]],
                 strip: Sequence[str] = (), commit_every: int = 0) -> int:
    """INSERT OR REPLACE（SQLite 原生；PG 由适配器改写 ON CONFLICT）。

    ``commit_every``：每 N 行提交一次（大库 48 万行单事务在远程实例上会被断连殃及全局，
    2026-10-29 实测）；0 = 不中途提交。失败前已提交的批次靠调用方的幂等清理覆盖。
    """
    if not rows:
        return 0
    existing = set(_table_columns(conn, table))
    if not existing:
        raise NeutralImportError(f"目标库缺表: {table}")
    drop = set(strip) | {"fts"}  # canonical_chunk_fts 生成列不可写
    columns = [c for c in rows[0] if c in existing and c not in drop]
    if not columns:
        raise NeutralImportError(f"目标表 {table} 无可写列")
    col_list = ",".join(f'"{c}"' for c in columns)
    marks = ",".join("?" for _ in columns)
    count = 0
    for row in rows:
        conn.execute(
            f'INSERT OR REPLACE INTO "{table}" ({col_list}) VALUES ({marks})',
            [row.get(c) for c in columns],
        )
        count += 1
        if commit_every and count % commit_every == 0:
            conn.commit()
    return count


def _sync_pg_sequences(conn: Any) -> None:
    """PG 侧显式自增列导入后同步序列（doc_blocks 等 BIGSERIAL 表）。"""
    from .pg_support import is_pg

    if not is_pg():
        return
    for table in ("doc_blocks", "parse_task_steps", "parse_stage_steps", "parse_records"):
        conn.execute(
            "SELECT setval(pg_get_serial_sequence(%s, 'id'), "
            "COALESCE((SELECT MAX(id) FROM " + table + "), 0) + 1, false)",
            (table,),
        )


# ---- 导入主体 ----------------------------------------------------------------


def _group_docs(documents: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [row for row in documents if str(row.get("doc_id") or "")]


def _build_canonical_document(
    doc_row: Dict[str, Any],
    rows: Dict[str, List[Dict[str, Any]]],
    doc_id: str,
) -> Any:
    """从模型形状行重建 CanonicalDocument（pydantic 负责嵌套对象验证）。"""
    from .models.types import CanonicalDocument

    doc_id = str(doc_row.get("doc_id") or doc_id)
    return CanonicalDocument(
        **doc_row,
        pages=[r for r in rows["pages"] if r.get("doc_id") == doc_id],
        blocks=[r for r in rows["blocks"] if r.get("doc_id") == doc_id],
        outlines=[r for r in rows["outlines"] if r.get("doc_id") == doc_id],
        chunks=[r for r in rows["chunks"] if r.get("doc_id") == doc_id],
        tables=[r for r in rows["tables"] if r.get("doc_id") == doc_id],
        citation_targets=[r for r in rows["citation_targets"] if r.get("doc_id") == doc_id],
    )


def _insert_parse_records(data_root: Path, lib_id: str, nodes: Sequence[Dict[str, Any]]) -> int:
    """给导入的 document 节点补 parse_records 行（legacy 导入器同口径）。"""
    from .parse_records_store import connect as pr_connect, init_schema as pr_init

    docs = [n for n in nodes if str(n.get("type") or "") == "document"]
    if not docs:
        return 0
    conn = pr_connect()
    try:
        pr_init(conn)
        created = 0
        for node in docs:
            doc_id = str(node.get("id") or "")
            if not doc_id:
                continue
            if conn.execute(
                "SELECT 1 FROM parse_records WHERE doc_id = ? LIMIT 1", (doc_id,)
            ).fetchone():
                continue
            fp = str(node.get("file_path") or "")
            f = Path(fp)
            target = f if f.is_absolute() else data_root / fp
            size = target.stat().st_size if target.is_file() else 0
            name = target.name if fp else str(node.get("title") or doc_id)
            fmt = target.suffix.lower() if fp else ""
            conn.execute(
                "INSERT INTO parse_records "
                "(doc_id, task_id, uploaded_by, api_key_id, file_name, file_format, file_size, "
                " status, error, created_at, library_id, stages) "
                "VALUES (?,?,?,?,?,?,?, ?, NULL, ?, ?, ?)",
                (
                    doc_id, f"import:{lib_id}:{doc_id}", "语料包导入", None,
                    name, fmt, size, "completed",
                    str(node.get("created_at") or _now()), lib_id, "",
                ),
            )
            created += 1
        conn.commit()
        _sync_pg_sequences(conn)
        conn.commit()
        return created
    finally:
        conn.close()


def _verify(lib_id: str, lib: _LibPackage, svc: Any, expect_vectors: int) -> Dict[str, int]:
    counts = lib.counts
    canonical_store = svc._canonical_store_for(lib_id)
    index_store = svc._index_store_for(lib_id)
    actual: Dict[str, int] = {}
    canonical_map = {
        "docs": ("canonical_documents", "library_id"),
        "chunks": ("canonical_chunks", None),
        "blocks": ("canonical_blocks", None),
        "pages": ("canonical_pages", None),
        "outlines": ("canonical_outlines", None),
        "tables": ("canonical_tables", None),
        "citations": ("canonical_citation_targets", None),
    }
    for key, (table, direct_col) in canonical_map.items():
        expected = int(counts.get(key) or 0)
        if direct_col:
            sql = f"SELECT COUNT(*) FROM {table} WHERE {direct_col} = ?"
            params: Tuple[Any, ...] = (lib_id,)
        else:
            sql = (f"SELECT COUNT(*) FROM {table} t JOIN canonical_documents d "
                   "ON t.doc_id = d.doc_id WHERE d.library_id = ?")
            params = (lib_id,)
        conn = canonical_store.connect()
        try:
            actual[key] = int(conn.execute(sql, params).fetchone()[0])
        finally:
            conn.close()
        if actual[key] != expected:
            raise NeutralImportError(
                f"[{lib_id}] {table} 对账失败: {actual[key]} != {expected}")
    for key, table in (("doc_blocks", "doc_blocks"), ("segments", "document_segments")):
        expected = int(counts.get(key) or 0)
        conn = index_store.connect()
        try:
            actual[key] = int(conn.execute(
                f"SELECT COUNT(*) FROM {table} t JOIN canonical_documents d "
                "ON t.doc_id = d.doc_id WHERE d.library_id = ?",
                (lib_id,),
            ).fetchone()[0])
        finally:
            conn.close()
        if actual[key] != expected:
            raise NeutralImportError(
                f"[{lib_id}] {table} 对账失败: {actual[key]} != {expected}")
    got_vectors = int(svc.vector_store.count_records(lib_id))
    actual["vectors"] = got_vectors
    if got_vectors != expect_vectors:
        raise NeutralImportError(
            f"[{lib_id}] vectors 对账失败: {got_vectors} != {expect_vectors}")
    return actual


_ALL_STAGES = ("registry", "files", "canonical", "index", "meta", "records", "vectors", "verify", "analyze")


def import_neutral_bundle(
    package_path: str | Path,
    *,
    apply: bool = False,
    libraries: Optional[Sequence[str]] = None,
    data_root: Optional[Path] = None,
    with_vectors: bool = True,
    on_stage: Optional[Callable[[str, str], None]] = None,
    stages: Optional[Sequence[str]] = None,
    allow_existing: bool = False,
) -> Dict[str, Any]:
    """预检（apply=False）或应用（apply=True）中性 v2 包。目标档位由 KB_STACK 决定。

    ``stages``：只跑指定阶段（断点续跑，如 index,meta,records,vectors,verify,analyze），缺省全部；
    ``allow_existing``：目标已有同 id 库时不拒绝（各阶段幂等：canonical clear+insert、
    块按 doc 清后重插、segments 主键 REPLACE、向量 upsert、文件存在即跳过）。
    """
    data_root = Path(data_root).resolve() if data_root else library_registry.resolve_data_root()
    _sections = set(stages) if stages else set(_ALL_STAGES)

    def _want(name: str) -> bool:
        return name in _sections

    def stage(name: str, message: str) -> None:
        if on_stage is not None:
            on_stage(name, message)

    outer, manifest, lib_packages = _open_bundle(package_path)
    try:
        selected = [lb for lb in lib_packages
                    if not libraries or lb.library_id in set(libraries)]
        if libraries:
            missing = sorted(set(libraries) - {lb.library_id for lb in selected})
            if missing:
                raise NeutralImportError(f"包内缺库: {missing}")
        if not selected:
            raise NeutralImportError("没有选中任何库")

        # ---- 预检 ----
        registered = {r.library_id for r in library_registry.list_libraries(include_retired=False)
                      if r.status != library_registry.STATUS_RETIRED}
        clashes = sorted({lb.library_id for lb in selected} & registered)
        if clashes and not allow_existing:
            raise NeutralImportError(
                f"目标已存在同 id 库: {clashes}；重导请先按库删除（kb_corpus_delete --library-id），"
                "或加 allow_existing 走断点续跑（各阶段幂等）")
        plans: List[Dict[str, Any]] = []
        for lb in selected:
            for arc in lb.files_index:
                lb.verify_entry_sha256(arc)
            plans.append({
                "lib": lb,
                "library_id": lb.library_id,
                "counts": lb.counts,
                "dimension": int(lb.manifest.get("dimension") or 0),
            })
        if not apply:
            return {
                "mode": "dry-run",
                "package": str(package_path),
                "stack": _stack_name(),
                "libraries": [{
                    "library_id": p["library_id"],
                    "counts": p["counts"],
                    "dimension": p["dimension"],
                    "files": len(p["lib"].files_index),
                } for p in plans],
            }

        # ---- 应用 ----
        svc = get_docs_service()
        from .corpus_package import _is_lib_root_sqlite

        scratch = Path(tempfile.mkdtemp(prefix="kb-neutral-import-"))
        completed: List[str] = []
        try:
            for p in plans:
                lib = p["lib"]
                lib_id = p["library_id"]
                meta_rows = _read_json_stream(lib, "meta/rows.json")
                registry_payload = _read_json_stream(lib, "registry/rows.json")
                source_row = (registry_payload.get("libraries") or [{}])[0]
                target_group = (str(source_row.get("group_name") or "")
                                or lib.manifest.get("group_name")
                                or library_registry.DEFAULT_GROUP)
                libraries_dir = _target_libraries_dir(target_group)

                if _want("registry"):
                    # 1) registry 先写（组路由依赖注册行）：collection=library_id 独立桶
                    stage("registry", f"{lib_id}: 写注册表")
                    sqlite_file = library_registry._DEFAULT_SQLITE_FILE if _is_pg_stack() \
                        else libraries_dir.rstrip("/") + f"/{lib_id}/index.sqlite"
                    library_registry.register_library(
                        lib_id,
                        name=str(source_row.get("name") or lib_id),
                        description=str(source_row.get("description") or ""),
                        group_name=target_group,
                        sqlite_file=sqlite_file,
                        collection=lib_id,
                        status=library_registry.STATUS_ACTIVE,
                    )
                    completed.append(f"{lib_id}:registry")

                if _want("files"):
                    # 2) files：按 data 根相对路径落盘（原文 + 解析产物不进 PG）
                    stage("files", f"{lib_id}: 复制文档树")
                    for arc in lib.files_index:
                        if not arc.startswith("files/"):
                            continue
                        rel = arc[6:]
                        if _is_lib_root_sqlite(rel):
                            continue
                        dst = data_root / rel
                        if dst.exists():
                            continue  # 幂等重导：文件树已存在不覆盖
                        dst.parent.mkdir(parents=True, exist_ok=True)
                        with lib.open_entry(arc) as src, dst.open("wb") as out:
                            shutil.copyfileobj(src, out, READ_CHUNK)
                    completed.append(f"{lib_id}:files")

                if _want("canonical"):
                    # 3) canonical：逐文档重建 CanonicalDocument 走既有 save_document 写路径
                    stage("canonical", f"{lib_id}: 写 canonical + FTS")
                    rows: Dict[str, List[Dict[str, Any]]] = {}
                    for table in ("documents", "pages", "blocks", "outlines",
                                  "chunks", "tables", "citation_targets"):
                        rows[table] = list(lib.jsonl_rows(f"canonical/{table}.jsonl.gz"))
                    canonical_store = svc._canonical_store_for(lib_id)
                    for doc_row in rows["documents"]:
                        doc_id = str(doc_row.get("doc_id") or "")
                        if not doc_id:
                            continue
                        document = _build_canonical_document(doc_row, rows, doc_id)
                        canonical_store.save_document(document)
                    completed.append(f"{lib_id}:canonical")

                if _want("index"):
                    # 4) index：doc_blocks / document_segments 行级 upsert（id 剥离自增）
                    #    分批提交：大库 48 万行塞一个事务，远程实例断连即全盘失败（2026-10-29 实测）
                    stage("index", f"{lib_id}: 写块索引与片段投影")
                    index_store = svc._index_store_for(lib_id)
                    doc_blocks = [
                        {k: v for k, v in r.items() if k != "id"}
                        for r in lib.jsonl_rows("index/doc_blocks.jsonl.gz")
                    ]
                    # SQLite 允许 TEXT PRIMARY KEY 存 NULL：源里 id 为空的 segment 行补稳定 id
                    segments_rows = []
                    for r in lib.jsonl_rows("index/document_segments.jsonl.gz"):
                        if not r.get("id"):
                            r["id"] = ":".join(str(r.get(k) or "") for k in
                                               ("doc_id", "strategy", "item_type", "order_index"))
                        segments_rows.append(r)
                    # block_uid 是唯一索引而非主键，REPLACE 语义覆盖不到：先按包内 doc 清旧行
                    for doc_id in dict.fromkeys(
                            str(r.get("doc_id") or "") for r in doc_blocks):
                        if doc_id:
                            index_store.clear_doc_blocks(doc_id)
                    conn = index_store.connect()
                    try:
                        _upsert_rows(conn, "doc_blocks", doc_blocks, commit_every=2000)
                        _upsert_rows(conn, "document_segments", segments_rows, commit_every=2000)
                        _sync_pg_sequences(conn)
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        conn.close()
                    completed.append(f"{lib_id}:index")

                if _want("meta"):
                    # 5) meta：nodes / tree_node / libraries 行级 upsert
                    stage("meta", f"{lib_id}: 写业务元数据")
                    meta_nodes = [r for r in meta_rows.get("nodes", []) if str(r.get("library_id") or "") == lib_id]
                    meta_tree = [r for r in meta_rows.get("tree_nodes", []) if str(r.get("scope_id") or "") == lib_id]
                    meta_libs = [r for r in meta_rows.get("libraries", []) if str(r.get("id") or "") == lib_id]
                    conn = svc.meta_store.connect()
                    try:
                        _upsert_rows(conn, "nodes", meta_nodes)
                        _upsert_rows(conn, "tree_node", meta_tree)
                        _upsert_rows(conn, "libraries", meta_libs)
                        conn.commit()
                    except Exception:
                        conn.rollback()
                        raise
                    finally:
                        conn.close()
                    completed.append(f"{lib_id}:meta")

                if _want("records"):
                    # 6) 台账：按 nodes 重建 parse_records
                    stage("records", f"{lib_id}: 补上传台账")
                    _insert_parse_records(data_root, lib_id, meta_nodes)
                    completed.append(f"{lib_id}:records")

                expect_vectors = int(p["counts"].get("vectors") or 0)
                if with_vectors and expect_vectors > 0 and _want("vectors"):
                    # 7) vectors：parquet → VectorRecord → upsert（不经快照、不经 reembed）
                    stage("vectors", f"{lib_id}: 写入向量（{expect_vectors} 点）")
                    hnsw_dropped = False
                    if _is_pg_stack():
                        from .pg_support import drop_vector_hnsw_index

                        _c = svc.vector_store._conn()
                        try:
                            hnsw_dropped = drop_vector_hnsw_index(_c)
                        finally:
                            _c.close()
                        if hnsw_dropped:
                            logger.info("[%s] 已摘 HNSW 索引，导完重建", lib_id)
                    written = 0
                    batch: List[VectorRecord] = []
                    for record in _iter_parquet_records(lib, f"vectors/{lib_id}.parquet"):
                        if not record.library_id:
                            record = record.model_copy(update={"library_id": lib_id})
                        batch.append(record)
                        if len(batch) >= _UPSERT_BATCH:
                            written += svc.vector_store.upsert_records(batch, collection=lib_id)
                            batch = []
                    if batch:
                        written += svc.vector_store.upsert_records(batch, collection=lib_id)
                    if _is_pg_stack() and hnsw_dropped:
                        from .pg_support import recreate_vector_hnsw_index

                        _c = svc.vector_store._conn()
                        try:
                            recreate_vector_hnsw_index(_c)
                        finally:
                            _c.close()
                        logger.info("[%s] HNSW 索引已重建", lib_id)
                    if written != expect_vectors:
                        raise NeutralImportError(
                            f"[{lib_id}] 向量写入数不符: {written} != {expect_vectors}"
                            "（空向量被跳过? 检查包内 parquet）")
                completed.append(f"{lib_id}:vectors")

                if _want("verify"):
                    # 8) 对账
                    stage("verify", f"{lib_id}: 逐表对账")
                    expect_vector_count = int(p["counts"].get("vectors") or 0) if with_vectors else 0
                    actual = _verify(lib_id, lib, svc, expect_vector_count)
                    completed.append(f"{lib_id}:verify")
                    p["actual"] = actual
            # 9) ANALYZE：批量导入后 planner 无统计会选错 plan（检索 1.5s→16s 实测），且报告要新鲜
            if _is_pg_stack() and _want("analyze"):
                from .pg_support import pg_connect

                stage("analyze", "ANALYZE 更新 planner 统计")
                _c = pg_connect()
                try:
                    _c.execute("SET max_parallel_maintenance_workers = 0")
                    _c.execute("ANALYZE")
                    _c.commit()
                finally:
                    _c.close()
                completed.append("analyze")
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return {
            "mode": "applied",
            "package": str(package_path),
            "stack": _stack_name(),
            "libraries": [p["library_id"] for p in plans],
            "completed": completed,
            "verify": {p["library_id"]: p.get("actual") for p in plans},
        }
    finally:
        outer.close()


def _read_json_stream(lib: _LibPackage, arcname: str) -> Dict[str, Any]:
    import gzip
    import io

    with lib.open_entry(arcname) as fh:
        data = gzip.GzipFile(fileobj=io.BytesIO(fh.read())) if arcname.endswith(".gz") else fh
        return json.loads(data.read().decode("utf-8"))


def _iter_parquet_records(lib: _LibPackage, arcname: str) -> Iterator[VectorRecord]:
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "中性包导入需要 pyarrow（docs-core[pg] extra）：pip install 'pyarrow>=15'") from exc
    with lib.open_entry(arcname) as fh:
        table = pq.read_table(fh)
        cols = {name: table.column(name).to_pylist() for name in (
            "record_id", "doc_id", "entity_type", "entity_id",
            "content", "content_hash", "metadata", "library_id", "embedding")}
    for i in range(table.num_rows):
        metadata_raw = cols["metadata"][i]
        try:
            metadata = json.loads(metadata_raw) if metadata_raw else {}
        except ValueError:
            metadata = {}
        yield VectorRecord(
            record_id=cols["record_id"][i],
            doc_id=cols["doc_id"][i],
            entity_type=cols["entity_type"][i],
            entity_id=cols["entity_id"][i],
            content=cols["content"][i] or "",
            content_hash=cols["content_hash"][i] or "",
            metadata=metadata if isinstance(metadata, dict) else {},
            embedding=[float(v) for v in (cols["embedding"][i] or [])],
            library_id=cols["library_id"][i] or "",
        )


def _is_pg_stack() -> bool:
    from .pg_support import is_pg

    return is_pg()


def _stack_name() -> str:
    from .pg_support import kb_stack

    return kb_stack()


__all__ = ["NeutralImportError", "import_neutral_bundle"]
