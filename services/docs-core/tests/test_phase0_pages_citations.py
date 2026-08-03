"""Phase 0 契约测试：pages 构造 + printed_page_label 落库 + 迁移。"""

import sqlite3
from pathlib import Path

import pytest

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
from docs_core.ingest.canonical.builder import (
    build_canonical_document_from_popoblocks,
    build_canonical_document,
)
from fixtures.popo_fixtures import EMPTY_TREE, build_noise_fixture


def _popo_doc_pages():
    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", build_noise_fixture(), EMPTY_TREE
    )
    return blocks, outlines, pages


def test_popoblocks_document_carries_pages(tmp_path: Path) -> None:
    blocks, outlines, pages = _popo_doc_pages()
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1",
        title="", blocks=blocks, outlines=outlines, pages=pages,
    )
    assert document.pages, "document.pages 必须非空"
    by_idx = {p.page_idx: p for p in document.pages}
    assert by_idx[0].printed_page_label == "12"


def test_canonical_pages_persisted_with_label(tmp_path: Path) -> None:
    from docs_core.write.store.canonical_sql_store import CanonicalSQLiteStore

    blocks, outlines, pages = _popo_doc_pages()
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1",
        title="", blocks=blocks, outlines=outlines, pages=pages,
    )
    store = CanonicalSQLiteStore(db_path=tmp_path / "index.sqlite")
    store.save_document(document)

    conn = sqlite3.connect(tmp_path / "index.sqlite")
    try:
        rows = conn.execute(
            "SELECT page_idx, printed_page_label FROM canonical_pages WHERE doc_id = ? ORDER BY page_idx",
            ("doc-1",),
        ).fetchall()
    finally:
        conn.close()
    assert rows == [(0, "12"), (1, "13")]


def test_solo_build_canonical_document_builds_pages(tmp_path: Path) -> None:
    # 无 graph 文件时 load_source_blocks 回退 mineru_blocks（空），pages 从 blocks 推导
    document = build_canonical_document(library_id="lib-x", doc_id="doc-x")
    assert document.pages == []
    # 直接以 blocks 构造 pages 的逻辑在 build_pages_from_blocks 单测覆盖


def test_build_pages_from_blocks() -> None:
    from docs_core.ingest.canonical.builder import build_pages_from_blocks
    from docs_core.ingest.canonical.types import CanonicalBlock, CanonicalPage

    blocks = [
        CanonicalBlock(block_id="b1", doc_id="d", page_idx=0),
        CanonicalBlock(block_id="b2", doc_id="d", page_idx=2),
    ]
    pages = build_pages_from_blocks(blocks)
    assert [p.page_idx for p in pages] == [0, 1, 2]
    assert all(isinstance(p, CanonicalPage) for p in pages)


def test_old_db_migration_adds_columns(tmp_path: Path) -> None:
    """旧库（无 printed_page_label / raw_type 列）升级后 ALTER 成功且旧数据可读。"""
    db_path = tmp_path / "old_index.sqlite"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            """CREATE TABLE canonical_blocks (
                block_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, page_idx INTEGER NOT NULL,
                block_type TEXT NOT NULL, text TEXT, text_clean TEXT, bbox_json TEXT,
                reading_order INTEGER NOT NULL, title_level INTEGER, section_path TEXT,
                source TEXT, source_ref TEXT, parent_block_id TEXT,
                inherited_chapter TEXT, entity_tags_json TEXT, conditions_json TEXT,
                exam_tags_json TEXT, clause_id TEXT, contd_target_id TEXT,
                image_assoc_id TEXT, table_merge_id TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE canonical_pages (
                doc_id TEXT NOT NULL, page_idx INTEGER NOT NULL,
                width REAL NOT NULL, height REAL NOT NULL,
                rotation INTEGER NOT NULL, image_path TEXT,
                PRIMARY KEY (doc_id, page_idx)
            )"""
        )
        conn.execute(
            """CREATE TABLE canonical_citation_targets (
                row_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, target_id TEXT NOT NULL,
                target_type TEXT NOT NULL, page_idx INTEGER NOT NULL, bbox_json TEXT,
                section_path TEXT, display_title TEXT, snippet TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE canonical_documents (
            doc_id TEXT PRIMARY KEY, library_id TEXT NOT NULL, title TEXT NOT NULL,
            source_file_name TEXT, source_file_type TEXT, schema_version TEXT,
            parse_version TEXT, language TEXT, page_count INTEGER NOT NULL, status TEXT NOT NULL,
            created_at TEXT, updated_at TEXT
        )""")
        conn.execute(
            "INSERT INTO canonical_blocks (block_id, doc_id, page_idx, block_type, text, text_clean, reading_order) VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("old-b1", "old-doc", 0, "title", "旧标题", "旧标题", 0),
        )
        conn.execute(
            "INSERT INTO canonical_pages (doc_id, page_idx, width, height, rotation) VALUES (?, ?, ?, ?, ?)",
            ("old-doc", 0, 100.0, 200.0, 0),
        )
        conn.commit()
    finally:
        conn.close()

    from docs_core.write.store.canonical_sql_store import CanonicalSQLiteStore

    store = CanonicalSQLiteStore(db_path=db_path)
    conn = sqlite3.connect(db_path)
    try:
        blocks_cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_blocks)")]
        pages_cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_pages)")]
        targets_cols = [r[1] for r in conn.execute("PRAGMA table_info(canonical_citation_targets)")]
    finally:
        conn.close()
    assert "raw_type" in blocks_cols
    assert "printed_page_label" in pages_cols
    assert "printed_page_label" in targets_cols
    # 旧数据升级后可读
    conn = sqlite3.connect(db_path)
    try:
        old_block = conn.execute(
            "SELECT block_id, raw_type FROM canonical_blocks WHERE block_id = ?", ("old-b1",)
        ).fetchone()
        old_page = conn.execute(
            "SELECT doc_id, printed_page_label FROM canonical_pages WHERE doc_id = ?", ("old-doc",)
        ).fetchone()
    finally:
        conn.close()
    assert old_block is not None and old_block[1] is None
    assert old_page is not None and old_page[1] is None
    assert store is not None
