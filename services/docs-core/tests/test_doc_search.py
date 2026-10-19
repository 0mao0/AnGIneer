"""doc_search：文档级聚合 + matter 归并 + 批量读页（不依赖真实库）。"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "shared" / "src"))

from docs_core.step09_query import doc_search  # noqa: E402


def _build_db(path: Path) -> None:
    conn = sqlite3.connect(str(path))
    conn.executescript(
        """
        CREATE TABLE canonical_documents(
            doc_id TEXT PRIMARY KEY, title TEXT, page_count INTEGER DEFAULT 1,
            library_id TEXT DEFAULT 'lib'
        );
        CREATE TABLE canonical_chunks(
            chunk_id TEXT PRIMARY KEY, doc_id TEXT, text_clean TEXT, page_start INTEGER DEFAULT 0
        );
        CREATE VIRTUAL TABLE canonical_chunk_fts USING fts5(
            chunk_id UNINDEXED, doc_id UNINDEXED, chunk_type UNINDEXED,
            section_path, text_clean UNINDEXED, text_ngrams, tokenize='unicode61'
        );
        CREATE TABLE doc_blocks(
            doc_id TEXT, page_idx INTEGER, block_seq INTEGER, block_type TEXT, title_path TEXT
        );
        """
    )
    docs = [
        ("d1", "second-request-strategy-memo.docx", "1001-00001", "Second Request strategy memo", 0),
        ("d1", "second-request-strategy-memo.docx", "1001-00001", "FTC issued a Second Request to the parties", 1),
        ("d2", "matter-closing-memo.docx", "1001-00002", "No second request was issued in this matter", 0),
        ("d3", "hsr-filing-cover-letter.docx", "1001-00002", "HSR filing cover letter", 0),
        ("d4", "2409.16644v2.pdf", "1001-00003", "Paper body about memes", 0),
    ]
    for idx, (doc_id, name, matter, text, page) in enumerate(docs, 1):
        chunk_id = f"c{idx}"
        conn.execute(
            "insert into canonical_chunks(chunk_id, doc_id, text_clean, page_start) values (?,?,?,?)",
            (chunk_id, doc_id, text, page),
        )
        conn.execute(
            "insert or ignore into canonical_documents(doc_id, title, page_count) values (?,?,1)",
            (doc_id, name),
        )
        conn.execute(
            "insert into canonical_chunk_fts(chunk_id, doc_id, chunk_type, section_path, text_clean, text_ngrams) "
            "values (?,?,?,?,?,?)",
            (chunk_id, doc_id, "content", "", text, text.lower()),
        )
    conn.executemany(
        "insert into doc_blocks(doc_id, page_idx, block_seq, block_type, title_path) values (?,?,?,?,?)",
        [
            ("d1", 0, 1, "title", "Second Request Strategy Memo"),
            ("d2", 0, 1, "title", "Matter Closing Memo"),
            ("d4", 0, 1, "title", "More than Memes: Conspiracy Theories on Telegram"),
        ],
    )
    conn.commit()
    conn.close()


@pytest.fixture()
def library_db(tmp_path, monkeypatch):
    db = tmp_path / "index.sqlite"
    _build_db(db)
    monkeypatch.setattr(doc_search, "_connect", lambda library_id: _conn(db))
    conn = sqlite3.connect(str(db))
    doc_search.ensure_catalog(conn)
    rows = [
        ("d1", "lib", "1001-00001", "Antitrust", "1001-00001/Antitrust/second-request-strategy-memo.docx",
         "second-request-strategy-memo.docx", "docx", "test", ""),
        ("d2", "lib", "1001-00002", "Memos", "1001-00002/Memos/matter-closing-memo.docx",
         "matter-closing-memo.docx", "docx", "test", ""),
        ("d3", "lib", "1001-00002", "HSR", "1001-00002/HSR/hsr-filing-cover-letter.docx",
         "hsr-filing-cover-letter.docx", "docx", "test", ""),
        ("d4", "lib", "1001-00003", "", "1001-00003/2409.16644v2.pdf",
         "2409.16644v2.pdf", "pdf", "test", ""),
    ]
    conn.executemany(
        "insert into doc_catalog(doc_id, library_id, matter_id, folder, rel_path, filename, doc_type, source, updated_at) "
        "values (?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db


def _conn(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def test_search_groups_by_matter_and_omits_duplicate_docs(library_db):
    result = doc_search.search_documents(library_id="lib", query="second request", limit=10)
    assert result["total_matters"] == 2
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001", "1001-00002"]
    assert result["matters"][0]["best"]["title"] == "second-request-strategy-memo.docx"
    # catalog 存在时不重复下发 docs 清单（避免 payload 翻倍）
    assert "docs" not in result


def test_backfill_semantic_fields(library_db):
    conn = _conn(library_db)
    try:
        stats = doc_search.backfill_semantic_fields(conn, "lib")
        cov = doc_search.catalog_semantic_coverage(conn, "lib")
        row = conn.execute(
            "select title_semantic, doc_type_semantic from doc_catalog where doc_id='d4'"
        ).fetchone()
    finally:
        conn.close()
    assert stats["with_title"] == 4
    assert row["title_semantic"].startswith("More than Memes")
    assert cov["title_block_rate"] == 0.75


def test_catalog_filter_matches_semantic_title(library_db):
    # 文件名是 arXiv 编号，靠首屏标题命中（标题里有 "on" 分隔，逐词匹配而非整串）
    conn = _conn(library_db)
    try:
        doc_search.backfill_semantic_fields(conn, "lib")
    finally:
        conn.close()
    result = doc_search.search_documents(
        library_id="lib", query="", limit=10, filename_contains=["conspiracy theories telegram"]
    )
    ids = {m["best"]["doc_id"] for m in result["matters"]}
    assert "d4" in ids
    # 编号文件名展示时改用语义标题
    card = next(m for m in result["matters"] if m["best"]["doc_id"] == "d4")
    assert "Memes" in card["best"]["title"]


def test_search_without_catalog_returns_docs(tmp_path, monkeypatch):
    db = tmp_path / "plain.sqlite"
    _build_db(db)
    monkeypatch.setattr(doc_search, "_connect", lambda library_id: _conn(db))
    result = doc_search.search_documents(library_id="lib", query="second request", limit=10)
    assert result["catalog"] is False
    assert "docs" in result
    assert result["docs"]
    assert result["docs"][0]["title"] == "second-request-strategy-memo.docx"


def test_catalog_predicate_marks_matter_card(library_db):
    # 目录谓词：文件名含 "second request"（连字符归一）的文档 → 带 catalog_hit 的 matter 卡
    result = doc_search.search_documents(
        library_id="lib", query="", limit=10, filename_contains=["second request"]
    )
    card = next(m for m in result["matters"] if m["matter_id"] == "1001-00001")
    assert card.get("catalog_hit") is True
    assert card["matched_docs"] == ["second-request-strategy-memo.docx"]
    assert result["filter"]["catalog_docs"] == 1


def test_list_matters(library_db):
    result = doc_search.list_matters("lib")
    assert result["catalog"] is True
    assert result["total"] == 3
    ids = [m["matter_id"] for m in result["matters"]]
    assert ids == ["1001-00001", "1001-00002", "1001-00003"]


def test_list_matters_without_catalog(tmp_path, monkeypatch):
    db = tmp_path / "plain2.sqlite"
    _build_db(db)
    monkeypatch.setattr(doc_search, "_connect", lambda library_id: _conn(db))
    assert doc_search.list_matters("lib")["catalog"] is False


@pytest.mark.parametrize("name,expected", [
    ("GB 17380-1998 中国海区水中建(构)筑物标志规定.pdf", "standard"),
    ("GB_T 17872-2009 江海直达货船船型尺度系列.pdf", "standard"),
    ("DB 13_T 5154-2019 高速公路高性能混凝土应用技术规程.pdf", "standard"),
    ("JT_T 828-2019 公路水运试验检测数据报告编制导则.pdf", "standard"),
    ("2024年度检测报告.pdf", "report"),
    ("second-request-strategy-memo.docx", "memo"),
    ("credit-agreement-execution.docx", "agreement"),
    ("2409.16644v2.pdf", "other"),
])
def test_classify_doc_type(name, expected):
    assert doc_search.classify_doc_type(name) == expected


def test_read_documents_head_and_match(library_db):
    head = doc_search.read_documents(library_id="lib", doc_ids=["d1"], max_chars_per_doc=500)
    doc = head["docs"][0]
    assert doc["matter_id"] == "1001-00001"
    assert "[p1]" in doc["text"] and "Second Request" in doc["text"]

    matched = doc_search.read_documents(
        library_id="lib", doc_ids=["d1"], query="issued", mode="match", max_chars_per_doc=500
    )
    assert "issued" in matched["docs"][0]["text"].lower()


def test_read_documents_caps_ids(library_db):
    ids = [f"d{i}" for i in range(12)]
    result = doc_search.read_documents(library_id="lib", doc_ids=ids)
    assert len(result["docs"]) <= doc_search.MAX_READ_DOCS
