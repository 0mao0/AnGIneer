"""第 10 步对外产物导出：按文档导出 structure / index / graph 产物。

索引库与图谱库是全库共享的 sqlite，不能整库交付给外部客户（会泄漏其他文档数据），
因此这里按 doc_id 导出该文档自己的行到独立临时 sqlite 文件。
"""
import logging
import shutil
import sqlite3
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, List, Optional

import docs_core.paths as paths

logger = logging.getLogger(__name__)

# 索引库中按 doc_id 导出的普通表
_INDEX_TABLES = (
    "canonical_documents",
    "canonical_pages",
    "canonical_blocks",
    "canonical_outlines",
    "canonical_chunks",
    "canonical_tables",
    "canonical_citation_targets",
    "canonical_vectors",
)

# 图谱库中按 doc_id/library_id 导出的表
_GRAPH_TABLES = (
    "graph_relations",
    "graph_principles",
    "graph_examples",
    "graph_warnings",
    "graph_frameworks",
)


def _has_rows(db_path: Path, table: str, where: str, params: List[object]) -> bool:
    if not db_path.exists():
        return False
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            row = conn.execute(f"SELECT 1 FROM {table} WHERE {where} LIMIT 1", params).fetchone()
            return row is not None
        finally:
            conn.close()
    except Exception:
        return False


def _table_columns(conn: sqlite3.Connection, table: str) -> List[str]:
    return [row[1] for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()]


def _copy_table(
    dst: sqlite3.Connection,
    src: sqlite3.Connection,
    table: str,
    where: str,
    params: List[object],
) -> bool:
    """把 src 表中满足 where 的行复制到 dst（同名列），成功返回 True。"""
    cols = _table_columns(src, table)
    if "doc_id" not in cols:
        return False
    col_list = ", ".join(f'"{c}"' for c in cols)
    dst.execute(
        f'CREATE TABLE "{table}" AS SELECT {col_list} FROM src."{table}" WHERE {where}',
        params,
    )
    return True


def _export_sqlite_common(
    src_db: Path,
    dst_dir: Path,
    file_name: str,
    tables: tuple,
    doc_id: str,
    where_by_table: Optional[Dict[str, str]] = None,
    params_by_table: Optional[Dict[str, List[object]]] = None,
    fts_table: Optional[str] = None,
) -> Path:
    where_by_table = where_by_table or {}
    params_by_table = params_by_table or {}
    dst_path = dst_dir / file_name
    src = sqlite3.connect(str(src_db))
    dst = sqlite3.connect(str(dst_path))
    try:
        dst.execute("ATTACH DATABASE ? AS src", (str(src_db),))
        for table in tables:
            try:
                if _copy_table(
                    dst,
                    src,
                    table,
                    where_by_table.get(table, "doc_id = ?"),
                    params_by_table.get(table, [doc_id]),
                ):
                    logger.debug("exported %s rows -> %s", table, file_name)
            except Exception as exc:
                logger.warning("export table %s skipped: %s", table, exc)

        # FTS5 虚拟表单独处理（不能 CREATE TABLE AS）
        if fts_table:
            cols = _table_columns(src, fts_table)
            if cols:
                col_list = ", ".join(f'"{c}"' for c in cols)
                try:
                    dst.execute(f"CREATE VIRTUAL TABLE {fts_table} USING fts5({col_list})")
                    dst.execute(
                        f'INSERT INTO {fts_table} ({col_list}) SELECT {col_list} FROM src."{fts_table}" WHERE doc_id = ?',
                        [doc_id],
                    )
                except Exception as exc:
                    logger.warning("export fts table %s skipped: %s", fts_table, exc)
        dst.commit()
    finally:
        src.close()
        dst.close()
    return dst_path


def list_doc_artifacts(library_id: str, doc_id: str) -> List[Dict[str, object]]:
    """返回该文档当前可下载的产物清单。"""
    items: List[Dict[str, object]] = []

    parsed_md = paths.get_parsed_markdown_path(library_id, doc_id)
    if parsed_md.exists():
        items.append({
            "name": "content.md",
            "kind": "markdown",
            "size": parsed_md.stat().st_size,
        })

    images_dir = paths.get_parsed_dir(library_id, doc_id) / "images"
    if images_dir.is_dir() and any(p.is_file() for p in images_dir.rglob("*")):
        items.append({
            "name": "images.zip",
            "kind": "images",
            "size": None,
        })

    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    if jsonl_path.exists():
        items.append({
            "name": "doc_blocks_graph.jsonl",
            "kind": "structure",
            "size": jsonl_path.stat().st_size,
        })
    meta_path = paths.get_graph_meta_path(library_id, doc_id)
    if meta_path.exists():
        items.append({
            "name": "doc_blocks_graph_meta.json",
            "kind": "structure",
            "size": meta_path.stat().st_size,
        })

    index_db = paths.resolve_knowledge_index_db_path()
    if _has_rows(index_db, "canonical_chunks", "doc_id = ?", [doc_id]) or _has_rows(
        index_db, "canonical_vectors", "doc_id = ?", [doc_id]
    ):
        items.append({"name": "index.sqlite", "kind": "index", "size": None})

    graph_db = paths.resolve_graph_db_path()
    if _has_rows(graph_db, "graph_relations", "library_id = ? AND doc_id = ?", [library_id, doc_id]):
        items.append({"name": "graph.sqlite", "kind": "graph", "size": None})

    return items


def export_markdown(library_id: str, doc_id: str) -> Path:
    """返回该文档解析出的 content.md 路径（前端预览与人工阅读的主产物）。"""
    path = paths.get_parsed_markdown_path(library_id, doc_id)
    if not path.exists():
        raise FileNotFoundError(f"文档 Markdown 产物不存在: {path}")
    return path


def export_images_zip(library_id: str, doc_id: str) -> Path:
    """把该文档 content.md 引用的 images/ 目录打包为 images.zip（保留 images/ 前缀）。"""
    images_dir = paths.get_parsed_dir(library_id, doc_id) / "images"
    if not images_dir.is_dir() or not any(p.is_file() for p in images_dir.rglob("*")):
        raise FileNotFoundError(f"文档图片目录不存在或为空: {images_dir}")

    dst_dir = Path(tempfile.mkdtemp(prefix=f"images-{doc_id}-"))
    zip_path = dst_dir / "images.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_path in sorted(images_dir.rglob("*")):
                if file_path.is_file():
                    arcname = f"images/{file_path.relative_to(images_dir).as_posix()}"
                    zf.write(file_path, arcname=arcname)
        return zip_path
    except Exception:
        shutil.rmtree(dst_dir, ignore_errors=True)
        raise


def export_index_db(library_id: str, doc_id: str) -> Path:
    """导出该文档的索引数据（chunks/blocks/pages/vectors + FTS）到独立 sqlite。"""
    src_db = paths.resolve_knowledge_index_db_path()
    if not src_db.exists():
        raise FileNotFoundError(f"索引库不存在: {src_db}")
    dst_dir = Path(tempfile.mkdtemp(prefix=f"artifacts-{doc_id}-"))
    try:
        return _export_sqlite_common(
            src_db=src_db,
            dst_dir=dst_dir,
            file_name="index.sqlite",
            tables=_INDEX_TABLES,
            doc_id=doc_id,
            fts_table="canonical_chunk_fts",
        )
    except Exception:
        shutil.rmtree(dst_dir, ignore_errors=True)
        raise


def export_graph_db(library_id: str, doc_id: str) -> Path:
    """导出该文档的图谱数据（关系 + 相关实体 + 原则/示例/警告/框架）到独立 sqlite。"""
    src_db = paths.resolve_graph_db_path()
    if not src_db.exists():
        raise FileNotFoundError(f"图谱库不存在: {src_db}")

    src = sqlite3.connect(str(src_db))
    try:
        rows = src.execute(
            "SELECT source_id, target_id FROM graph_relations WHERE library_id = ? AND doc_id = ?",
            (library_id, doc_id),
        ).fetchall()
        entity_ids = sorted({rid for row in rows for rid in row if rid})
    finally:
        src.close()

    where_by_table = {
        "graph_relations": "library_id = ? AND doc_id = ?",
        "graph_principles": "doc_id = ?",
        "graph_examples": "doc_id = ?",
        "graph_warnings": "doc_id = ?",
        "graph_frameworks": "doc_id = ?",
    }
    params_by_table = {
        "graph_relations": [library_id, doc_id],
        "graph_principles": [doc_id],
        "graph_examples": [doc_id],
        "graph_warnings": [doc_id],
        "graph_frameworks": [doc_id],
    }

    dst_dir = Path(tempfile.mkdtemp(prefix=f"artifacts-{doc_id}-"))
    try:
        dst_path = _export_sqlite_common(
            src_db=src_db,
            dst_dir=dst_dir,
            file_name="graph.sqlite",
            tables=_GRAPH_TABLES,
            doc_id=doc_id,
            where_by_table=where_by_table,
            params_by_table=params_by_table,
        )
        # 导出该文档关系引用的实体（实体是全局共享的，只导出被本文档引用的部分）
        if entity_ids:
            dst = sqlite3.connect(str(dst_path))
            src_entity = sqlite3.connect(str(src_db))
            try:
                placeholders = ",".join("?" for _ in entity_ids)
                dst.execute("ATTACH DATABASE ? AS src", (str(src_db),))
                for table in ("graph_entities", "principle_entities", "example_entities", "warning_entities"):
                    try:
                        cols = _table_columns(src_entity, table)
                        col_list = ", ".join(f'"{c}"' for c in cols)
                        dst.execute(
                            f'CREATE TABLE "{table}" AS SELECT {col_list} FROM src."{table}" WHERE entity_id IN ({placeholders})',
                            entity_ids,
                        )
                    except Exception as exc:
                        logger.warning("export entity table %s skipped: %s", table, exc)
                dst.commit()
            finally:
                src_entity.close()
                dst.close()
        return dst_path
    except Exception:
        shutil.rmtree(dst_dir, ignore_errors=True)
        raise


def remove_export_dir(path: Path) -> None:
    """清理导出临时目录（供 FileResponse 后台任务调用）。"""
    if path and path.exists():
        shutil.rmtree(path, ignore_errors=True)
