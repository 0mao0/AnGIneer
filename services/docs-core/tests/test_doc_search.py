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
    ("中华人民共和国港口法(2018年修正).pdf", "law"),
    ("建设工程质量管理条例.pdf", "law"),
    ("XX管理办法（2018）.pdf", "policy"),
    ("图像分割算法研究.pdf", "other"),
    ("Dodd-Frank Act.pdf", "law"),
    ("second-request-strategy-memo.docx", "memo"),
    ("credit-agreement-execution.docx", "agreement"),
    ("2409.16644v2.pdf", "other"),
])
def test_classify_doc_type(name, expected):
    assert doc_search.classify_doc_type(name) == expected


def test_group_identity():
    assert doc_search._group_identity("1001-00001", "", "d1") == {
        "group_id": "1001-00001", "group_kind": "case"}
    assert doc_search._group_identity("", "HSR", "d1") == {
        "group_id": "folder:HSR", "group_kind": "folder"}
    assert doc_search._group_identity("", "", "d1") == {
        "group_id": "doc:d1", "group_kind": "doc"}


def test_upsert_catalog_doc_derives_group(library_db):
    out = doc_search.upsert_catalog_doc(
        library_id="lib", doc_id="d9", filename="2024年度检测报告.pdf", rel_path="报告/2024"
    )
    assert out["group_kind"] == "folder"
    assert out["doc_type"] == "report"
    conn = _conn(library_db)
    try:
        row = conn.execute("select title_semantic, folder from doc_catalog where doc_id='d9'").fetchone()
        stats = doc_search.list_matters("lib")
    finally:
        conn.close()
    assert row["title_semantic"] == "2024年度检测报告"
    assert row["folder"] == "报告"
    assert stats["group_kinds"]["folder"] >= 1


def test_catalog_write_switch(monkeypatch):
    monkeypatch.delenv("ANGINEER_CATALOG_WRITE", raising=False)
    assert doc_search.catalog_write_enabled()
    monkeypatch.setenv("ANGINEER_CATALOG_WRITE", "0")
    assert not doc_search.catalog_write_enabled()


def test_refresh_doc_semantics(library_db):
    out = doc_search.refresh_doc_semantics("lib", "d1")
    assert out["title"] == "Second Request Strategy Memo"
    assert out["title_source"] == "block"
    assert out["doc_type"] == "memo"
    # 没有目录行：跳过，由回填脚本兜底
    assert doc_search.refresh_doc_semantics("lib", "d5").get("skipped")


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


def test_read_documents_match_falls_back_to_or(library_db):
    # 术语写法不一（"MFN" vs "Most Favored Nation"）时，全词 AND 会落空；
    # 退到 OR 后应命中有 "issued" 的那段，而不是回落到整篇开头。
    result = doc_search.read_documents(
        library_id="lib", doc_ids=["d1"], query="issued unicorn dragon", mode="match"
    )
    text = result["docs"][0]["text"].lower()
    assert "issued" in text
    assert "strategy memo" not in text


def test_read_documents_section_locates_clause(library_db):
    conn = _conn(library_db)
    try:
        conn.execute(
            "insert into canonical_documents(doc_id, title, page_count) values ('d6','credit-agreement.docx',3)"
        )
        conn.executemany(
            "insert into canonical_chunks(chunk_id, doc_id, text_clean, page_start) values (?,?,?,?)",
            [
                ("c10", "d6", "Preamble recitals and definitions", 0),
                ("c11", "d6", "Section 2.15 — Incremental Revolving Commitments (Accordion)", 2),
                ("c12", "d6", "(d) MFN same-pricing and equal-treatment terms apply.", 2),
            ],
        )
        conn.commit()
    finally:
        conn.close()
    hit = doc_search.read_documents(library_id="lib", doc_ids=["d6"], section="2.15")
    doc = hit["docs"][0]
    assert doc["section_found"] is True
    assert "Section 2.15" in doc["text"] and "MFN same-pricing" in doc["text"]
    assert "Preamble" not in doc["text"]

    miss = doc_search.read_documents(library_id="lib", doc_ids=["d6"], section="9.99")
    assert miss["docs"][0]["section_found"] is False
    assert "Preamble" in miss["docs"][0]["text"]  # 找不到章节 → 回退普通读页


# ---------------------------------------------------------------------------
# 时间维度：日期抽取 / 回填 / 排序 / 区间过滤
# ---------------------------------------------------------------------------


def _set_dates(path: Path, dates: dict) -> None:
    conn = _conn(path)
    try:
        conn.executemany(
            "update doc_catalog set doc_date=?, date_source=?, date_confidence=? where doc_id=?",
            [(value, "text" if value else "none", "high" if value else "none", doc_id)
             for doc_id, value in dates.items()],
        )
        conn.commit()
    finally:
        conn.close()


def test_catalog_alters_legacy_table_without_date_columns(tmp_path):
    db = tmp_path / "legacy.sqlite"
    conn = sqlite3.connect(str(db))
    conn.executescript(
        """
        CREATE TABLE doc_catalog (
            doc_id TEXT PRIMARY KEY, library_id TEXT NOT NULL,
            matter_id TEXT NOT NULL DEFAULT '', folder TEXT NOT NULL DEFAULT '',
            rel_path TEXT NOT NULL DEFAULT '', filename TEXT NOT NULL DEFAULT '',
            doc_type TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        """
    )
    conn.execute("insert into doc_catalog(doc_id, library_id, filename) values ('d1','lib','memo.docx')")
    conn.commit()
    doc_search.ensure_catalog(conn)
    cols = {row[1] for row in conn.execute("pragma table_info(doc_catalog)")}
    row = conn.execute("select doc_date, date_source, date_confidence from doc_catalog").fetchone()
    conn.close()
    assert {"doc_date", "date_source", "date_confidence"} <= cols
    assert row == ("", "none", "none")


@pytest.mark.parametrize("text,expected", [
    ("This Agreement is dated as of July 16, 2024 by and between the parties.", ("2024-07-16", "text", "high")),
    ("DATED: 2024-07-16", ("2024-07-16", "text", "high")),
    ("Effective as of March 3, 2025, the Company shall...", ("2025-03-03", "text", "high")),
    ("本协议于2024年7月16日签署。", ("2024-07-16", "text", "high")),
    ("2024 年 7 月发布", ("2024-07-01", "text", "low")),
    ("2024年年度报告", ("2024-07-01", "text", "low")),
    # 英文孤立年份不抽（引证页码/表格单元格噪声，实测把 2094 认成文档日期）
    ("Fiscal year 2024 results were strong", ("", "none", "none")),
    ("See Smith v. Jones, 123 F.3d 2094 (1998)", ("", "none", "none")),
    # 未来日期不可信
    ("This Agreement is dated as of July 16, 2094", ("", "none", "none")),
    ("No dates in this document at all", ("", "none", "none")),
])
def test_extract_date_from_text(text, expected):
    assert doc_search.extract_date_from_text(text) == expected


@pytest.mark.parametrize("name,expected", [
    ("credit-agreement-2024-07-16.docx", ("2024-07-16", "filename", "medium")),
    ("hsr-filing-20240716.pdf", ("2024-07-16", "filename", "medium")),
    ("2024年度检测报告.pdf", ("2024-07-01", "filename", "low")),
    ("合同2024年7月16日.docx", ("2024-07-16", "filename", "medium")),
    ("二〇二四年报告.pdf", ("", "none", "none")),
    ("second-request-strategy-memo.docx", ("", "none", "none")),
])
def test_extract_date_from_filename(name, expected):
    assert doc_search.extract_date_from_filename(name) == expected



def test_backfill_doc_dates_prefers_text_then_filename_then_mtime(library_db):
    def resolver(library_id, doc_id):
        return {"d3": "2022-05-06"}.get(doc_id, "")

    conn = _conn(library_db)
    try:
        conn.execute("alter table doc_blocks add column plain_text text")
        conn.execute(
            "insert into doc_blocks(doc_id, page_idx, block_seq, block_type, title_path, plain_text) "
            "values ('d1', 0, 9, 'para', '', 'Dated as of July 16, 2024 — Second Request strategy')"
        )
        conn.execute("update doc_catalog set filename='matter-closing-2025-01-05.docx' where doc_id='d2'")
        conn.commit()
        stats = doc_search.backfill_doc_dates("lib", conn=conn, mtime_resolver=resolver)
        rows = {
            r["doc_id"]: (r["doc_date"], r["date_source"], r["date_confidence"])
            for r in conn.execute("select doc_id, doc_date, date_source, date_confidence from doc_catalog")
        }
        cov = doc_search.catalog_date_coverage(conn, "lib")
        second = doc_search.backfill_doc_dates("lib", conn=conn, mtime_resolver=resolver)
    finally:
        conn.close()
    assert rows["d1"] == ("2024-07-16", "text", "high")
    assert rows["d2"] == ("2025-01-05", "filename", "medium")
    assert rows["d3"] == ("2022-05-06", "mtime", "low")
    assert rows["d4"] == ("", "none", "none")
    assert stats["total"] == 4 and stats["with_date"] == 3
    assert stats["by_source"] == {"text": 1, "filename": 1, "mtime": 1, "none": 1}
    assert cov["with_date"] == 3 and cov["coverage"] == 0.75
    assert cov["date_min"] == "2022-05-06" and cov["date_max"] == "2025-01-05"
    # 幂等：第二次回填不再写行
    assert second["updated"] == 0


def test_search_date_desc_sorts_groups_and_keeps_empty_last(library_db):
    _set_dates(library_db, {"d1": "2024-07-16", "d2": "2025-01-05"})
    result = doc_search.search_documents(
        library_id="lib", query="", filename_contains=["memo"], limit=10, sort_by="date_desc"
    )
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00002", "1001-00001"]
    newest = result["matters"][0]
    assert newest["doc_date"] == "2025-01-05"
    assert newest["date_source"] == "text"
    assert newest["best"]["doc_date"] == "2025-01-05"
    assert result["date_sort"]["sort_by"] == "date_desc"

    _set_dates(library_db, {"d2": ""})
    result = doc_search.search_documents(
        library_id="lib", query="", filename_contains=["memo"], limit=10, sort_by="date_desc"
    )
    # 空日期排最后
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001", "1001-00002"]
    assert result["matters"][-1]["doc_date"] == ""


def test_search_date_asc(library_db):
    _set_dates(library_db, {"d1": "2024-07-16", "d2": "2023-01-05"})
    result = doc_search.search_documents(
        library_id="lib", query="", filename_contains=["memo"], limit=10, sort_by="date_asc"
    )
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00002", "1001-00001"]


def test_search_date_range_filter_excludes_undated(library_db):
    _set_dates(library_db, {"d1": "2024-07-16", "d2": ""})
    result = doc_search.search_documents(
        library_id="lib",
        query="",
        filename_contains=["memo"],
        limit=10,
        date_after="2024-01-01",
        date_before="2024-12-31",
    )
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001"]
    assert result["date_sort"]["date_after"] == "2024-01-01"
    assert result["date_sort"]["date_before"] == "2024-12-31"


def test_search_invalid_date_params_are_reported_not_applied(library_db):
    result = doc_search.search_documents(
        library_id="lib", query="second request", limit=10, sort_by="newest", date_after="07/16/2024"
    )
    # 非法参数不生效（仍按相关性），但要在结果里回显，便于模型自纠
    assert result["date_sort"]["sort_by"] == ""
    assert result["date_sort"]["date_after"] == ""
    assert result["date_sort"]["invalid"] == ["sort_by=newest", "date_after=07/16/2024"]
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001", "1001-00002"]


def test_search_default_has_no_date_fields(library_db):
    """不传日期参数时结果与改造前一致：无 date_sort、卡片无 doc_date。"""
    result = doc_search.search_documents(library_id="lib", query="second request", limit=10)
    assert "date_sort" not in result
    assert "doc_date" not in result["matters"][0]
    assert "doc_date" not in result["matters"][0]["best"]
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001", "1001-00002"]


def test_search_date_sort_without_catalog_errors(tmp_path, monkeypatch):
    db = tmp_path / "plain3.sqlite"
    _build_db(db)
    monkeypatch.setattr(doc_search, "_connect", lambda library_id: _conn(db))
    result = doc_search.search_documents(library_id="lib", query="second request", sort_by="date_desc")
    assert "error" in result


def test_mtime_dates_do_not_drive_sort_or_filter(library_db):
    """mtime 只是落盘时间：排序排在正文/文件名日期之后，且不参与区间过滤。"""
    conn = _conn(library_db)
    try:
        conn.execute(
            "update doc_catalog set doc_date='2026-10-13', date_source='mtime', date_confidence='low' "
            "where doc_id='d1'"
        )
        conn.execute(
            "update doc_catalog set doc_date='2024-01-05', date_source='text', date_confidence='high' "
            "where doc_id='d2'"
        )
        conn.commit()
    finally:
        conn.close()
    result = doc_search.search_documents(
        library_id="lib", query="", filename_contains=["memo"], limit=10, sort_by="date_desc"
    )
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00002", "1001-00001"]
    assert result["date_sort"]["dated_docs"] == 1
    assert result["date_sort"]["mtime_only_docs"] == 1

    filtered = doc_search.search_documents(
        library_id="lib",
        query="",
        filename_contains=["memo"],
        limit=10,
        date_after="2026-01-01",
    )
    assert filtered["matters"] == []  # mtime 2026-10-13 不算文档日期


# ---------------------------------------------------------------------------
# 实体范围（entity_contains）：先锁案件，再在案件内取最新/按类型过滤
# ---------------------------------------------------------------------------


def _add_engagement_letter(path: Path) -> None:
    """在 d1 所属 matter 里加一篇更高分的非 memo 文档，验证组内 best 仍取目录命中。"""
    conn = _conn(path)
    try:
        conn.execute(
            "insert into canonical_chunks(chunk_id, doc_id, text_clean, page_start) values (?,?,?,?)",
            ("c9", "d5", "FTC second request engagement letter second request strategy", 0),
        )
        conn.execute(
            "insert into canonical_documents(doc_id, title, page_count) values ('d5','engagement-letter.docx',1)"
        )
        conn.execute(
            "insert into canonical_chunk_fts(chunk_id, doc_id, chunk_type, section_path, text_clean, text_ngrams) "
            "values ('c9','d5','content','','FTC second request engagement letter second request strategy',"
            "'ftc second request engagement letter second request strategy')"
        )
        conn.execute(
            "insert into doc_catalog(doc_id, library_id, matter_id, folder, rel_path, filename, doc_type, "
            "source, updated_at) values ('d5','lib','1001-00001','Deal','1001-00001/Deal/engagement-letter.docx',"
            "'engagement-letter.docx','docx','test','')"
        )
        conn.commit()
    finally:
        conn.close()


def test_entity_scopes_candidates_to_matched_matters(library_db):
    # "FTC" 只出现在 d1（matter 1001-00001），"second request" 同时命中 d2
    result = doc_search.search_documents(
        library_id="lib", query="second request", entity_contains="FTC", limit=10
    )
    assert result["entity"]["matched_groups"] == 1
    assert result["total_matters"] == 1
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001"]
    assert result["entity"]["scoped_docs"] == 1


def test_entity_plus_filename_prefers_catalog_hit_as_best(library_db):
    _add_engagement_letter(library_db)
    result = doc_search.search_documents(
        library_id="lib",
        query="second request",
        entity_contains="FTC",
        filename_contains=["memo"],
        limit=10,
    )
    cards = {m["matter_id"]: m for m in result["matters"]}
    assert set(cards) == {"1001-00001"}  # d2 的 memo 不在实体案件内
    card = cards["1001-00001"]
    assert card["best"]["doc_id"] == "d1"  # 目录命中优先于分数更高的 d5
    assert card["catalog_hit"] is True
    assert card["matched_docs"] == ["second-request-strategy-memo.docx"]


def test_entity_only_returns_entity_docs_by_date(library_db):
    _set_dates(library_db, {"d1": "2024-07-16"})
    result = doc_search.search_documents(
        library_id="lib", query="", entity_contains="FTC", sort_by="date_desc", limit=10
    )
    assert result["entity"]["matched_docs"] == 1
    assert [m["matter_id"] for m in result["matters"]] == ["1001-00001"]
    assert result["matters"][0]["doc_date"] == "2024-07-16"


def test_entity_not_found_returns_error(library_db):
    result = doc_search.search_documents(
        library_id="lib", query="second request", entity_contains="Nonexistent Holdings", limit=10
    )
    assert "error" in result and "Nonexistent Holdings" in result["error"]


def test_entity_type_date_unique_hit_is_authoritative(library_db):
    _set_dates(library_db, {"d1": "2024-07-16"})
    result = doc_search.search_documents(
        library_id="lib",
        query="",
        entity_contains="FTC",
        filename_contains=["memo"],
        sort_by="date_desc",
        limit=10,
    )
    assert result["authoritative"]["doc_id"] == "d1"
    assert result["authoritative"]["doc_date"] == "2024-07-16"
    assert "必须基于该文档" in result["authoritative"]["instruction"]
    # 没给日期排序时不产生 authoritative（避免把普通目录查询当结论）
    plain = doc_search.search_documents(
        library_id="lib", query="", entity_contains="FTC", filename_contains=["memo"], limit=10
    )
    assert "authoritative" not in plain

