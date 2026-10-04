"""FTS 库过滤：library_ids 限定在求交前生效；跨组各查再合并。

种子写法以现码建表为准（计划校准点）：canonical_documents 的 title/page_count/status
为 NOT NULL；canonical_chunk_fts 的 text_clean 是 UNINDEXED（MATCH 不命中），
可检索列是 section_path 与 text_ngrams（CJK bigram 索引），故种子须灌 text_ngrams。
"""
from pathlib import Path

from docs_core.step05_sqlite_fts.store.canonical_sql_store import (
    CanonicalSQLiteStore,
    build_cjk_ngram_text,
)


def _seed_store(tmp_path: Path, name: str, rows: list[tuple[str, str, str]]) -> CanonicalSQLiteStore:
    store = CanonicalSQLiteStore(db_path=tmp_path / name)
    with store.connect() as conn:
        for doc_id, library_id, text in rows:
            conn.execute(
                "INSERT OR REPLACE INTO canonical_documents"
                " (doc_id, library_id, title, page_count, status) VALUES (?, ?, ?, ?, ?)",
                (doc_id, library_id, doc_id, 1, "done"),
            )
            conn.execute(
                "INSERT INTO canonical_chunk_fts (chunk_id, doc_id, chunk_type, section_path, text_clean, text_ngrams)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (f"{doc_id}:c1", doc_id, "content", "", text, build_cjk_ngram_text(text)),
            )
    return store


class TestStoreSearchChunkFtsLibraryFilter:
    def test_filter_restricts_before_limit(self, tmp_path):
        store = _seed_store(tmp_path, "g.sqlite", [
            ("d1", "libA", "混凝土 抗压强度 试验方法"),
            ("d2", "libB", "混凝土 抗压强度 标准值"),
            ("d3", "libB", "混凝土 抗压强度 设计值"),
        ])
        hits = store.search_chunk_fts(None, "混凝土 抗压强度", limit=10, library_ids=["libB"])
        assert {h["doc_id"] for h in hits} == {"d2", "d3"}

    def test_no_filter_returns_all(self, tmp_path):
        store = _seed_store(tmp_path, "g.sqlite", [
            ("d1", "libA", "混凝土 抗压强度 试验方法"),
            ("d2", "libB", "混凝土 抗压强度 标准值"),
        ])
        hits = store.search_chunk_fts(None, "混凝土 抗压强度", limit=10)
        assert {h["doc_id"] for h in hits} == {"d1", "d2"}
