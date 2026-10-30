"""中性语料包导出 v2（engine-neutral，KB_STACK 双源同产物）。

与 legacy bundle（``corpus_package``，绑 Qdrant 快照 + SQLite 组库字节）相对，本模块产出
**引擎无关**的包：向量以 parquet 列文件承载，关系层以行级 JSONL 承载，导入端经存储抽象
写入 legacy 或 pg 均可（方案文档 §4.5「中性 v2 为必做项」）。

外层 bundle（zip）::

    manifest.json                    kind=bundle, format=neutral-v2, schema_version=3
    libraries/<library_id>.zip       每库小包：
      ├─ manifest.json               kind=library, counts{...}/dimension/files(sha256)
      ├─ registry/rows.json          本库 registry 行（legacy/pg 源同形状）
      ├─ meta/rows.json              nodes/tree_nodes/libraries 行
      ├─ files/…                     原文 + 解析产物（同 legacy 排除 mineru_raw/popo）
      ├─ canonical/*.jsonl.gz        documents/pages/blocks/outlines/chunks/tables/citation_targets
      ├─ index/doc_blocks.jsonl.gz   + index/document_segments.jsonl.gz
      └─ vectors/<library_id>.parquet  record_id/doc_id/entity_*/content/content_hash/
                                       metadata(JSON 字符串)/library_id/embedding(float32)

导出源：``get_docs_service()``（KB_STACK=legacy → SQLite+Qdrant；KB_STACK=pg → PostgreSQL+pgvector），
向量面经 ``VectorStore.iter_records``（Qdrant=scroll、pgvector=SQL 分页），同模型零重嵌。
图/上传台账不在包内（与 legacy 包同口径：新部署图按需重建、台账从空开始）。
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import logging
import os
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple

from . import library_registry
from .corpus_package import DEFAULT_EXCLUDE_DIRS, PAGE_BASE, embed_model_from_env
from .docs_service import get_docs_service
from .models.vector_io import record_to_point_payload

logger = logging.getLogger(__name__)

NEUTRAL_FORMAT = "neutral-v2"
NEUTRAL_SCHEMA_VERSION = 3
READ_CHUNK = 1 << 20

_CANONICAL_FILES: Tuple[str, ...] = (
    "documents", "pages", "blocks", "outlines", "chunks", "tables", "citation_targets",
)
_INDEX_TABLES: Tuple[str, ...] = ("doc_blocks", "document_segments")
_PARQUET_COLUMNS: Tuple[str, ...] = (
    "record_id", "doc_id", "entity_type", "entity_id",
    "content", "content_hash", "metadata", "library_id", "embedding",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_entry(zf: zipfile.ZipFile, arcname: str) -> str:
    h = hashlib.sha256()
    with zf.open(arcname) as fh:
        for chunk in iter(lambda: fh.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(READ_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- 行读取（经 store.connect()，SQLite 与 PG 适配器同一 SQL）-----------------


def _rows(store: Any, sql: str, params: Sequence[Any]) -> List[Dict[str, Any]]:
    conn = store.connect()
    try:
        return [dict(row) for row in conn.execute(sql, tuple(params)).fetchall()]
    finally:
        conn.close()


def _read_meta_rows(svc: Any, lib_id: str) -> Dict[str, List[dict]]:
    conn = svc.meta_store.connect()
    try:
        nodes = [dict(r) for r in conn.execute(
            "SELECT * FROM nodes WHERE library_id = ?", (lib_id,)).fetchall()]
        tree = [dict(r) for r in conn.execute(
            "SELECT * FROM tree_node WHERE scope_id = ?", (lib_id,)).fetchall()]
        libs = [dict(r) for r in conn.execute(
            "SELECT * FROM libraries WHERE id = ?", (lib_id,)).fetchall()]
    finally:
        conn.close()
    return {"nodes": nodes, "tree_nodes": tree, "libraries": libs}


def _read_registry_rows(lib_id: str) -> Tuple[List[dict], List[dict]]:
    record = library_registry.get_library(lib_id)
    if record is None:
        return [], []
    row = record.to_dict()
    group = None
    for g in library_registry.list_custom_groups():
        if g.group_name == record.group_name:
            group = g.to_dict()
            break
    return [row], ([group] if group else [])


# canonical 行以 **模型形状**（model_dump(mode="json)"）承载：bbox/citation_targets 等
# 是对象而非 _json 字符串列——导入端 ``CanonicalDocument(**row)`` 直接重建，形状即契约。
_DOC_NESTED = ("pages", "blocks", "outlines", "chunks", "tables", "citation_targets")


def _read_canonical_docs(svc: Any, lib_id: str) -> List[Any]:
    """整库 canonical 文档对象列表（经组路由 store.get_document，两后端同实现）。"""
    canonical_store = svc._canonical_store_for(lib_id)
    id_rows = _rows(canonical_store,
                    "SELECT doc_id FROM canonical_documents WHERE library_id = ?", (lib_id,))
    docs = []
    for row in id_rows:
        document = canonical_store.get_document(str(row["doc_id"]))
        if document is not None:
            docs.append(document)
    return docs


def _split_canonical_docs(docs: List[Any]) -> Tuple[Dict[str, List[dict]], Dict[str, int]]:
    rows: Dict[str, List[dict]] = {
        "documents": [], "pages": [], "blocks": [], "outlines": [],
        "chunks": [], "tables": [], "citation_targets": [],
    }
    counts = {"docs": 0, "chunks": 0, "blocks": 0, "pages": 0,
              "outlines": 0, "tables": 0, "citations": 0}
    for document in docs:
        payload = document.model_dump(mode="json")
        rows["documents"].append({k: v for k, v in payload.items() if k not in _DOC_NESTED})
        rows["pages"].extend(payload["pages"])
        rows["blocks"].extend(payload["blocks"])
        rows["outlines"].extend(payload["outlines"])
        rows["chunks"].extend(payload["chunks"])
        rows["tables"].extend(payload["tables"])
        rows["citation_targets"].extend(payload["citation_targets"])
        counts["docs"] += 1
        counts["pages"] += len(payload["pages"])
        counts["blocks"] += len(payload["blocks"])
        counts["outlines"] += len(payload["outlines"])
        counts["chunks"] += len(payload["chunks"])
        counts["tables"] += len(payload["tables"])
        counts["citations"] += len(payload["citation_targets"])
    return rows, counts


def _read_index_rows(svc: Any, lib_id: str) -> Dict[str, List[dict]]:
    store = svc._index_store_for(lib_id)
    out: Dict[str, List[dict]] = {}
    for table in _INDEX_TABLES:
        out[table] = _rows(
            store,
            f"SELECT t.* FROM {table} t JOIN canonical_documents d ON t.doc_id = d.doc_id "
            "WHERE d.library_id = ?",
            (lib_id,),
        )
    return out


# ---- 向量 parquet ------------------------------------------------------------


def _vectors_to_parquet(records: Iterator[Any]) -> Tuple[bytes, int]:
    """向量记录流 → parquet 字节（pyarrow 惰性导入；中性包的唯一引擎绑定物格式）。"""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "中性导出需要 pyarrow（docs-core[pg] extra）：pip install 'pyarrow>=15'") from exc

    columns: Dict[str, List[Any]] = {name: [] for name in _PARQUET_COLUMNS}
    count = 0
    for record in records:
        payload = record_to_point_payload(record)
        columns["record_id"].append(str(payload["record_id"]))
        columns["doc_id"].append(str(payload["doc_id"]))
        columns["entity_type"].append(str(payload["entity_type"]))
        columns["entity_id"].append(str(payload["entity_id"]))
        columns["content"].append(str(payload["content"]))
        columns["content_hash"].append(str(payload["content_hash"]))
        columns["metadata"].append(json.dumps(payload["metadata"], ensure_ascii=False))
        columns["library_id"].append(str(payload["library_id"]))
        columns["embedding"].append([float(v) for v in (record.embedding or [])])
        count += 1
    table = pa.table({
        "record_id": pa.array(columns["record_id"], type=pa.string()),
        "doc_id": pa.array(columns["doc_id"], type=pa.string()),
        "entity_type": pa.array(columns["entity_type"], type=pa.string()),
        "entity_id": pa.array(columns["entity_id"], type=pa.string()),
        "content": pa.array(columns["content"], type=pa.string()),
        "content_hash": pa.array(columns["content_hash"], type=pa.string()),
        "metadata": pa.array(columns["metadata"], type=pa.string()),
        "library_id": pa.array(columns["library_id"], type=pa.string()),
        "embedding": pa.array(columns["embedding"], type=pa.list_(pa.float32())),
    })
    sink = io.BytesIO()
    pq.write_table(table, sink, compression="zstd")
    return sink.getvalue(), count


# ---- 包构造 -----------------------------------------------------------------


def _jsonl_gz_bytes(rows: Sequence[Dict[str, Any]]) -> bytes:
    buf = io.BytesIO()
    with gzip.GzipFile(fileobj=buf, mode="wb", compresslevel=6) as gz:
        for row in rows:
            gz.write((json.dumps(row, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
    return buf.getvalue()


def _json_bytes(payload: Any) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=1).encode("utf-8")


def export_neutral_bundle(
    libs: List[str],
    out_path: Path,
    *,
    exclude_dirs: Sequence[str] = DEFAULT_EXCLUDE_DIRS,
    on_stage: Optional[Callable[[str, str], None]] = None,
) -> Path:
    """导出中性 v2 bundle 到 out_path（.zip）。源由 KB_STACK 决定，产物形状一致。"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    svc = get_docs_service()
    embed_model = embed_model_from_env()
    bundle_manifest: Dict[str, Any] = {
        "kind": "bundle",
        "format": NEUTRAL_FORMAT,
        "schema_version": NEUTRAL_SCHEMA_VERSION,
        "created_at": _now(),
        "embed_model": embed_model,
        "page_base": PAGE_BASE,
        "libraries": [],
    }

    def stage(name: str, message: str) -> None:
        if on_stage is not None:
            on_stage(name, message)

    with tempfile.TemporaryDirectory(prefix="kb-neutral-export-") as tmp:
        tmp_dir = Path(tmp)
        lib_entries: List[Dict[str, Any]] = []
        for lib_id in libs:
            stage("collect", f"{lib_id}: 读取行级数据")
            if library_registry.get_library(lib_id) is None:
                raise ValueError(f"注册表缺库: {lib_id}")
            meta_rows = _read_meta_rows(svc, lib_id)
            registry_rows, group_rows = _read_registry_rows(lib_id)
            canonical_rows, doc_counts = _split_canonical_docs(_read_canonical_docs(svc, lib_id))
            index_rows = _read_index_rows(svc, lib_id)

            stage("vectors", f"{lib_id}: 直读向量存储")
            collection = library_registry.resolve_collection(lib_id)
            vector_store = svc.vector_store
            parquet_bytes, vector_count = _vectors_to_parquet(
                (r for r in vector_store.iter_records(collection, library_id=lib_id)
                 if (r.library_id or "") == lib_id or not (r.library_id or "")),
            )
            dimension = vector_store.get_existing_dimension(collection)

            stage("package", f"{lib_id}: 打包")
            lib_zip = tmp_dir / f"{lib_id}.zip"
            lib_manifest_files: Dict[str, Dict[str, Any]] = {}
            with zipfile.ZipFile(lib_zip, "w", zipfile.ZIP_DEFLATED) as zf:
                def add_bytes(arcname: str, data: bytes) -> None:
                    zf.writestr(arcname, data)
                    lib_manifest_files[arcname] = {"sha256": hashlib.sha256(data).hexdigest(),
                                                   "bytes": len(data)}

                for table in _CANONICAL_FILES:
                    add_bytes(f"canonical/{table}.jsonl.gz",
                              _jsonl_gz_bytes(canonical_rows.get(table) or []))
                for table in _INDEX_TABLES:
                    add_bytes(f"index/{table}.jsonl.gz",
                              _jsonl_gz_bytes(index_rows.get(table) or []))
                add_bytes("meta/rows.json", _json_bytes(meta_rows))
                add_bytes("registry/rows.json", _json_bytes({
                    "libraries": registry_rows, "groups": group_rows,
                }))
                vector_arc = f"vectors/{lib_id}.parquet"
                add_bytes(vector_arc, parquet_bytes)

                # files/：库目录树（跳过 lib 根 sqlite 与排除目录，同 legacy 口径）。
                # arc 用 **data 根相对路径**（knowledge/libraries/<lib>/...，与旧 bundle
                # _source_library_root 的 marker 解析兼容），导入按 data_root/rel 落位。
                from .corpus_package import _iter_doc_files, _is_lib_root_sqlite

                lib_root = library_registry.resolve_libraries_dir(lib_id) / lib_id
                try:
                    lib_root_rel = lib_root.resolve().relative_to(
                        library_registry.resolve_data_root().resolve()).as_posix()
                except ValueError:
                    lib_root_rel = f"knowledge/libraries/{lib_id}"
                for path, rel_in_lib, size in _iter_doc_files(lib_root, exclude_dirs):
                    if _is_lib_root_sqlite(rel_in_lib):
                        continue
                    arc = f"files/{lib_root_rel}/{rel_in_lib}"
                    with zf.open(arc, "w", force_zip64=True) as dst, path.open("rb") as src:
                        shutil.copyfileobj(src, dst, READ_CHUNK)
                    lib_manifest_files[arc] = {
                        "sha256": _sha256_entry(zf, arc), "bytes": size,
                    }

                counts = {
                    **doc_counts,
                    "doc_blocks": len(index_rows["doc_blocks"]),
                    "segments": len(index_rows["document_segments"]),
                    "vectors": vector_count,
                }
                lib_manifest = {
                    "kind": "library",
                    "format": NEUTRAL_FORMAT,
                    "schema_version": NEUTRAL_SCHEMA_VERSION,
                    "library_id": lib_id,
                    "name": (registry_rows[0].get("name") if registry_rows else "") or lib_id,
                    "group_name": (registry_rows[0].get("group_name") if registry_rows
                                   else library_registry.DEFAULT_GROUP),
                    "embed_model": embed_model,
                    "page_base": PAGE_BASE,
                    "dimension": int(dimension or 0),
                    "counts": counts,
                    "files": lib_manifest_files,
                    "warnings": [],
                }
                add_bytes("manifest.json", _json_bytes(lib_manifest))

            entry = {
                "library_id": lib_id,
                "name": lib_manifest["name"],
                "group_name": lib_manifest["group_name"],
                "entry": f"libraries/{lib_id}.zip",
                "sha256": _sha256_file(lib_zip),
                "bytes": lib_zip.stat().st_size,
                "counts": counts,
            }
            lib_entries.append(entry)
            bundle_manifest["libraries"].append(entry)

        with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as outer:
            outer.writestr("manifest.json", _json_bytes(bundle_manifest))
            for entry in lib_entries:
                with outer.open(entry["entry"], "w", force_zip64=True) as dst, \
                        (tmp_dir / f"{entry['library_id']}.zip").open("rb") as src:
                    shutil.copyfileobj(src, dst, READ_CHUNK)
    logger.info("中性包导出完成: %s (%d 库)", out_path, len(lib_entries))
    return out_path


__all__ = [
    "NEUTRAL_FORMAT",
    "NEUTRAL_SCHEMA_VERSION",
    "export_neutral_bundle",
]
