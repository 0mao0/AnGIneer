"""Canonical schema SQLite 持久化实现"""
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional

from docs_core.ingest.organize.types import (
    BoundingBox,
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
)
from docs_core.ingest.store.blocks_sql_store import create_connection, resolve_knowledge_index_db_path


# 统一序列化任JSON 字段
def _dump_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


# 统一反序列化任意 JSON 字段
def _load_json(payload: Optional[str], default: object) -> object:
    if not payload:
        return default
    try:
        return json.loads(payload)
    except Exception:
        return default


# 统一序列bbox 对象
def _dump_bbox(bbox: Optional[BoundingBox]) -> Optional[str]:
    if bbox is None:
        return None
    return _dump_json(bbox.model_dump(mode="json"))


# 统一反序列化 bbox 对象
def _load_bbox(payload: Optional[str]) -> Optional[BoundingBox]:
    data = _load_json(payload, None)
    if not isinstance(data, dict):
        return None
    return BoundingBox(**data)


class CanonicalSQLiteStore:
    """canonical document 持久化到 knowledge_index.sqlite"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or resolve_knowledge_index_db_path()
        self.init_schema()

    # 打开 canonical SQLite 连接
    def connect(self):
        return create_connection(self.db_path)

    # 初始canonical 相关表结构
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_documents (
                    doc_id TEXT PRIMARY KEY,
                    library_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    source_file_name TEXT,
                    source_file_type TEXT,
                    schema_version TEXT,
                    parse_version TEXT,
                    language TEXT,
                    page_count INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT,
                    updated_at TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_pages (
                    doc_id TEXT NOT NULL,
                    page_idx INTEGER NOT NULL,
                    width REAL NOT NULL,
                    height REAL NOT NULL,
                    rotation INTEGER NOT NULL,
                    image_path TEXT,
                    PRIMARY KEY (doc_id, page_idx)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_blocks (
                    block_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    page_idx INTEGER NOT NULL,
                    block_type TEXT NOT NULL,
                    text TEXT,
                    text_clean TEXT,
                    bbox_json TEXT,
                    reading_order INTEGER NOT NULL,
                    title_level INTEGER,
                    section_path TEXT,
                    source TEXT,
                    source_ref TEXT,
                    parent_block_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_outlines (
                    outline_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    level INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    section_path TEXT,
                    page_idx INTEGER NOT NULL,
                    anchor_block_id TEXT,
                    parent_outline_id TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_chunks (
                    chunk_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    chunk_type TEXT NOT NULL,
                    text TEXT,
                    text_clean TEXT,
                    token_count INTEGER NOT NULL,
                    section_path TEXT,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    source_block_ids_json TEXT,
                    citation_targets_json TEXT,
                    version TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_tables (
                    table_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    page_start INTEGER NOT NULL,
                    page_end INTEGER NOT NULL,
                    title TEXT,
                    caption TEXT,
                    bbox_json TEXT,
                    table_type TEXT,
                    header_rows_json TEXT,
                    body_rows_json TEXT,
                    units_json TEXT,
                    row_count INTEGER NOT NULL,
                    col_count INTEGER NOT NULL,
                    source_block_ids_json TEXT,
                    summary TEXT,
                    row_keys_json TEXT,
                    text_chunks_json TEXT,
                    version TEXT
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_citation_targets (
                    row_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    target_type TEXT NOT NULL,
                    page_idx INTEGER NOT NULL,
                    bbox_json TEXT,
                    section_path TEXT,
                    display_title TEXT,
                    snippet TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_blocks_doc_page ON canonical_blocks(doc_id, page_idx, reading_order)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_chunks_doc_type ON canonical_chunks(doc_id, chunk_type, page_start)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_chunks_doc_text ON canonical_chunks(doc_id, text_clean)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_tables_doc_type ON canonical_tables(doc_id, table_type, page_start)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_citations_doc_target ON canonical_citation_targets(doc_id, target_id)"
            )
            conn.commit()

    # 清理单个文档的全canonical 持久化数据
    def clear_document(self, doc_id: str) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM canonical_citation_targets WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_tables WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_chunks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_outlines WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_blocks WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_pages WHERE doc_id = ?", (doc_id,))
            conn.execute("DELETE FROM canonical_documents WHERE doc_id = ?", (doc_id,))
            conn.commit()

    # 持久化整canonical document
    def save_document(self, document: CanonicalDocument) -> dict[str, int]:
        now = datetime.now(timezone.utc).isoformat()
        created_at = document.created_at or now
        updated_at = document.updated_at or now
        self.clear_document(document.doc_id)
        citation_rows: List[tuple[str, str, str, str, int, Optional[str], str, str, str]] = []

        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO canonical_documents (
                    doc_id, library_id, title, source_file_name, source_file_type,
                    schema_version, parse_version, language, page_count, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    document.doc_id,
                    document.library_id,
                    document.title,
                    document.source_file_name,
                    document.source_file_type,
                    document.schema_version,
                    document.parse_version,
                    document.language,
                    document.page_count,
                    document.status,
                    created_at,
                    updated_at,
                ),
            )
            conn.executemany(
                """
                INSERT INTO canonical_pages (
                    doc_id, page_idx, width, height, rotation, image_path
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        page.doc_id,
                        page.page_idx,
                        page.width,
                        page.height,
                        page.rotation,
                        page.image_path,
                    )
                    for page in document.pages
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_blocks (
                    block_id, doc_id, page_idx, block_type, text, text_clean, bbox_json,
                    reading_order, title_level, section_path, source, source_ref, parent_block_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        block.block_id,
                        block.doc_id,
                        block.page_idx,
                        block.block_type,
                        block.text,
                        block.text_clean,
                        _dump_bbox(block.bbox),
                        block.reading_order,
                        block.title_level,
                        block.section_path,
                        block.source,
                        block.source_ref,
                        block.parent_block_id,
                    )
                    for block in document.blocks
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_outlines (
                    outline_id, doc_id, level, title, section_path, page_idx, anchor_block_id, parent_outline_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        outline.outline_id,
                        outline.doc_id,
                        outline.level,
                        outline.title,
                        outline.section_path,
                        outline.page_idx,
                        outline.anchor_block_id,
                        outline.parent_outline_id,
                    )
                    for outline in document.outlines
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_chunks (
                    chunk_id, doc_id, chunk_type, text, text_clean, token_count,
                    section_path, page_start, page_end, source_block_ids_json,
                    citation_targets_json, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        chunk.chunk_id,
                        chunk.doc_id,
                        chunk.chunk_type,
                        chunk.text,
                        chunk.text_clean,
                        chunk.token_count,
                        chunk.section_path,
                        chunk.page_start,
                        chunk.page_end,
                        _dump_json(chunk.source_block_ids),
                        _dump_json([target.model_dump(mode="json") for target in chunk.citation_targets]),
                        chunk.version,
                    )
                    for chunk in document.chunks
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_tables (
                    table_id, doc_id, page_start, page_end, title, caption, bbox_json,
                    table_type, header_rows_json, body_rows_json, units_json, row_count,
                    col_count, source_block_ids_json, summary, row_keys_json, text_chunks_json, version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        table.table_id,
                        table.doc_id,
                        table.page_start,
                        table.page_end,
                        table.title,
                        table.caption,
                        _dump_bbox(table.bbox),
                        table.table_type,
                        _dump_json(table.header_rows),
                        _dump_json(table.body_rows),
                        _dump_json(table.units),
                        table.row_count,
                        table.col_count,
                        _dump_json(table.source_block_ids),
                        table.summary,
                        _dump_json(table.row_keys),
                        _dump_json(table.text_chunks),
                        table.version,
                    )
                    for table in document.tables
                ],
            )
            for chunk in document.chunks:
                for target in chunk.citation_targets:
                    citation_rows.append(
                        (
                            f"cit-{uuid.uuid4().hex[:16]}",
                            target.doc_id,
                            target.target_id,
                            target.target_type,
                            target.page_idx,
                            _dump_bbox(target.bbox),
                            target.section_path,
                            target.display_title,
                            target.snippet,
                        )
                    )
            conn.executemany(
                """
                INSERT INTO canonical_citation_targets (
                    row_id, doc_id, target_id, target_type, page_idx, bbox_json, section_path, display_title, snippet
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                citation_rows,
            )
            conn.commit()

        return {
            "pages": len(document.pages),
            "blocks": len(document.blocks),
            "outlines": len(document.outlines),
            "chunks": len(document.chunks),
            "tables": len(document.tables),
            "citations": len(citation_rows),
        }

    # 读取整份 canonical document
    def get_document(self, doc_id: str) -> Optional[CanonicalDocument]:
        with self.connect() as conn:
            document_row = conn.execute(
                """
                SELECT doc_id, library_id, title, source_file_name, source_file_type,
                       schema_version, parse_version, language, page_count, status,
                       created_at, updated_at
                FROM canonical_documents
                WHERE doc_id = ?
                """,
                (doc_id,),
            ).fetchone()
            if not document_row:
                return None
            page_rows = conn.execute(
                """
                SELECT doc_id, page_idx, width, height, rotation, image_path
                FROM canonical_pages
                WHERE doc_id = ?
                ORDER BY page_idx ASC
                """,
                (doc_id,),
            ).fetchall()
            block_rows = conn.execute(
                """
                SELECT block_id, doc_id, page_idx, block_type, text, text_clean, bbox_json,
                       reading_order, title_level, section_path, source, source_ref, parent_block_id
                FROM canonical_blocks
                WHERE doc_id = ?
                ORDER BY page_idx ASC, reading_order ASC
                """,
                (doc_id,),
            ).fetchall()
            outline_rows = conn.execute(
                """
                SELECT outline_id, doc_id, level, title, section_path, page_idx, anchor_block_id, parent_outline_id
                FROM canonical_outlines
                WHERE doc_id = ?
                ORDER BY page_idx ASC, level ASC, outline_id ASC
                """,
                (doc_id,),
            ).fetchall()
            chunk_rows = conn.execute(
                """
                SELECT chunk_id, doc_id, chunk_type, text, text_clean, token_count,
                       section_path, page_start, page_end, source_block_ids_json,
                       citation_targets_json, version
                FROM canonical_chunks
                WHERE doc_id = ?
                ORDER BY page_start ASC, chunk_id ASC
                """,
                (doc_id,),
            ).fetchall()
            table_rows = conn.execute(
                """
                SELECT table_id, doc_id, page_start, page_end, title, caption, bbox_json,
                       table_type, header_rows_json, body_rows_json, units_json, row_count,
                       col_count, source_block_ids_json, summary, row_keys_json, text_chunks_json, version
                FROM canonical_tables
                WHERE doc_id = ?
                ORDER BY page_start ASC, table_id ASC
                """,
                (doc_id,),
            ).fetchall()

        return CanonicalDocument(
            doc_id=document_row["doc_id"],
            library_id=document_row["library_id"],
            title=document_row["title"],
            source_file_name=document_row["source_file_name"] or "",
            source_file_type=document_row["source_file_type"] or "pdf",
            schema_version=document_row["schema_version"] or "1.0.0",
            parse_version=document_row["parse_version"] or "0.1.0",
            language=document_row["language"] or "zh",
            page_count=int(document_row["page_count"] or 0),
            status=document_row["status"] or "pending",
            created_at=document_row["created_at"],
            updated_at=document_row["updated_at"],
            pages=[
                CanonicalPage(
                    doc_id=row["doc_id"],
                    page_idx=int(row["page_idx"] or 0),
                    width=float(row["width"] or 0.0),
                    height=float(row["height"] or 0.0),
                    rotation=int(row["rotation"] or 0),
                    image_path=row["image_path"],
                )
                for row in page_rows
            ],
            blocks=[
                CanonicalBlock(
                    block_id=row["block_id"],
                    doc_id=row["doc_id"],
                    page_idx=int(row["page_idx"] or 0),
                    block_type=row["block_type"] or "unknown",
                    text=row["text"] or "",
                    text_clean=row["text_clean"] or "",
                    bbox=_load_bbox(row["bbox_json"]),
                    reading_order=int(row["reading_order"] or 0),
                    title_level=row["title_level"],
                    section_path=row["section_path"] or "",
                    source=row["source"] or "mineru",
                    source_ref=row["source_ref"],
                    parent_block_id=row["parent_block_id"],
                )
                for row in block_rows
            ],
            outlines=[
                CanonicalOutlineNode(
                    outline_id=row["outline_id"],
                    doc_id=row["doc_id"],
                    level=int(row["level"] or 1),
                    title=row["title"],
                    section_path=row["section_path"] or "",
                    page_idx=int(row["page_idx"] or 0),
                    anchor_block_id=row["anchor_block_id"],
                    parent_outline_id=row["parent_outline_id"],
                )
                for row in outline_rows
            ],
            chunks=[
                CanonicalChunk(
                    chunk_id=row["chunk_id"],
                    doc_id=row["doc_id"],
                    chunk_type=row["chunk_type"] or "content",
                    text=row["text"] or "",
                    text_clean=row["text_clean"] or "",
                    token_count=int(row["token_count"] or 0),
                    section_path=row["section_path"] or "",
                    page_start=int(row["page_start"] or 0),
                    page_end=int(row["page_end"] or 0),
                    source_block_ids=list(_load_json(row["source_block_ids_json"], [])),
                    citation_targets=[
                        CitationTarget(**target)
                        for target in _load_json(row["citation_targets_json"], [])
                        if isinstance(target, dict)
                    ],
                    version=row["version"] or "0.1.0",
                )
                for row in chunk_rows
            ],
            tables=[
                CanonicalTable(
                    table_id=row["table_id"],
                    doc_id=row["doc_id"],
                    page_start=int(row["page_start"] or 0),
                    page_end=int(row["page_end"] or 0),
                    title=row["title"] or "",
                    caption=row["caption"] or "",
                    bbox=_load_bbox(row["bbox_json"]),
                    table_type=row["table_type"] or "hybrid",
                    header_rows=list(_load_json(row["header_rows_json"], [])),
                    body_rows=list(_load_json(row["body_rows_json"], [])),
                    units=list(_load_json(row["units_json"], [])),
                    row_count=int(row["row_count"] or 0),
                    col_count=int(row["col_count"] or 0),
                    source_block_ids=list(_load_json(row["source_block_ids_json"], [])),
                    summary=row["summary"] or "",
                    row_keys=list(_load_json(row["row_keys_json"], [])),
                    text_chunks=list(_load_json(row["text_chunks_json"], [])),
                    version=row["version"] or "0.1.0",
                )
                for row in table_rows
            ],
        )

    # 查询 canonical chunks，供 retrieval 主链直接消费
    def list_chunks(
        self,
        doc_id: str,
        chunk_types: Optional[Iterable[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalChunk]:
        sql = """
            SELECT chunk_id, doc_id, chunk_type, text, text_clean, token_count,
                   section_path, page_start, page_end, source_block_ids_json,
                   citation_targets_json, version
            FROM canonical_chunks
            WHERE doc_id = ?
        """
        params: List[object] = [doc_id]
        normalized_types = [item for item in (chunk_types or []) if item]
        if normalized_types:
            placeholders = ",".join(["?"] * len(normalized_types))
            sql += f" AND chunk_type IN ({placeholders})"
            params.extend(normalized_types)
        if keyword:
            sql += " AND (text LIKE ? OR text_clean LIKE ? OR section_path LIKE ?)"
            like_keyword = f"%{keyword}%"
            params.extend([like_keyword, like_keyword, like_keyword])
        sql += " ORDER BY page_start ASC, chunk_id ASC LIMIT ?"
        params.append(max(1, min(1000, limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            CanonicalChunk(
                chunk_id=row["chunk_id"],
                doc_id=row["doc_id"],
                chunk_type=row["chunk_type"] or "content",
                text=row["text"] or "",
                text_clean=row["text_clean"] or "",
                token_count=int(row["token_count"] or 0),
                section_path=row["section_path"] or "",
                page_start=int(row["page_start"] or 0),
                page_end=int(row["page_end"] or 0),
                source_block_ids=list(_load_json(row["source_block_ids_json"], [])),
                citation_targets=[
                    CitationTarget(**target)
                    for target in _load_json(row["citation_targets_json"], [])
                    if isinstance(target, dict)
                ],
                version=row["version"] or "0.1.0",
            )
            for row in rows
        ]

    # 查询 canonical blocks，供 debug fallback 检索使用
    def list_blocks(
        self,
        doc_id: str,
        block_types: Optional[Iterable[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 200,
    ) -> List[CanonicalBlock]:
        sql = """
            SELECT block_id, doc_id, page_idx, block_type, text, text_clean, bbox_json,
                   reading_order, title_level, section_path, source, source_ref, parent_block_id
            FROM canonical_blocks
            WHERE doc_id = ?
        """
        params: List[object] = [doc_id]
        normalized_types = [item for item in (block_types or []) if item]
        if normalized_types:
            placeholders = ",".join(["?"] * len(normalized_types))
            sql += f" AND block_type IN ({placeholders})"
            params.extend(normalized_types)
        if keyword:
            sql += " AND (text LIKE ? OR text_clean LIKE ? OR section_path LIKE ?)"
            like_keyword = f"%{keyword}%"
            params.extend([like_keyword, like_keyword, like_keyword])
        sql += " ORDER BY page_idx ASC, reading_order ASC LIMIT ?"
        params.append(max(1, min(1000, limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            CanonicalBlock(
                block_id=row["block_id"],
                doc_id=row["doc_id"],
                page_idx=int(row["page_idx"] or 0),
                block_type=row["block_type"] or "unknown",
                text=row["text"] or "",
                text_clean=row["text_clean"] or "",
                bbox=_load_bbox(row["bbox_json"]),
                reading_order=int(row["reading_order"] or 0),
                title_level=row["title_level"],
                section_path=row["section_path"] or "",
                source=row["source"] or "mineru",
                source_ref=row["source_ref"],
                parent_block_id=row["parent_block_id"],
            )
            for row in rows
        ]

    # 查询 canonical tables，供后续 table-aware retrieval schema lookup 使用
    def list_tables(
        self,
        doc_id: str,
        table_types: Optional[Iterable[str]] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
    ) -> List[CanonicalTable]:
        sql = """
            SELECT table_id, doc_id, page_start, page_end, title, caption, bbox_json,
                   table_type, header_rows_json, body_rows_json, units_json, row_count,
                   col_count, source_block_ids_json, summary, row_keys_json, text_chunks_json, version
            FROM canonical_tables
            WHERE doc_id = ?
        """
        params: List[object] = [doc_id]
        normalized_types = [item for item in (table_types or []) if item]
        if normalized_types:
            placeholders = ",".join(["?"] * len(normalized_types))
            sql += f" AND table_type IN ({placeholders})"
            params.extend(normalized_types)
        if keyword:
            sql += " AND (title LIKE ? OR caption LIKE ? OR summary LIKE ?)"
            like_keyword = f"%{keyword}%"
            params.extend([like_keyword, like_keyword, like_keyword])
        sql += " ORDER BY page_start ASC, table_id ASC LIMIT ?"
        params.append(max(1, min(500, limit)))
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            CanonicalTable(
                table_id=row["table_id"],
                doc_id=row["doc_id"],
                page_start=int(row["page_start"] or 0),
                page_end=int(row["page_end"] or 0),
                title=row["title"] or "",
                caption=row["caption"] or "",
                bbox=_load_bbox(row["bbox_json"]),
                table_type=row["table_type"] or "hybrid",
                header_rows=list(_load_json(row["header_rows_json"], [])),
                body_rows=list(_load_json(row["body_rows_json"], [])),
                units=list(_load_json(row["units_json"], [])),
                row_count=int(row["row_count"] or 0),
                col_count=int(row["col_count"] or 0),
                source_block_ids=list(_load_json(row["source_block_ids_json"], [])),
                summary=row["summary"] or "",
                row_keys=list(_load_json(row["row_keys_json"], [])),
                text_chunks=list(_load_json(row["text_chunks_json"], [])),
                version=row["version"] or "0.1.0",
            )
            for row in rows
        ]
