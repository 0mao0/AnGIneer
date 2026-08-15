# -*- coding: utf-8 -*-
"""检索文本处理与条款号直达的单元测试。

覆盖：
- build_cjk_ngram_text / _build_fts_match_query（CJK bigram 索引与查询构造）
- extract_clause_refs_strict（上下文门控的条款号抽取）
- list_blocks_by_clause_refs（clause_id 双向层级精确查询）
- search_chunk_fts（bigram 索引下的中文 FTS 召回）
"""
import tempfile
import unittest
from pathlib import Path

from docs_core.step05_sqlite_fts.store.canonical_sql_store import (
    CanonicalSQLiteStore,
    _build_fts_match_query,
    build_cjk_ngram_text,
)
from docs_core.step09_query.retrieval.clause_resolver import extract_clause_refs_strict


class TestCjkNgramText(unittest.TestCase):
    def test_cjk_run_expanded_to_bigrams(self):
        result = build_cjk_ngram_text("码头前沿")
        self.assertIn("码头", result.split())
        self.assertIn("头前", result.split())
        self.assertIn("前沿", result.split())

    def test_single_cjk_char_kept(self):
        result = build_cjk_ngram_text("高")
        self.assertIn("高", result.split())

    def test_non_cjk_preserved(self):
        result = build_cjk_ngram_text("H4%波高")
        self.assertIn("H4%", result)
        self.assertIn("波高", result.split())

    def test_empty_input(self):
        self.assertEqual(build_cjk_ngram_text(""), " ".join(build_cjk_ngram_text("").split()) or "")


class TestBuildFtsMatchQuery(unittest.TestCase):
    def test_cjk_query_expanded(self):
        match = _build_fts_match_query("底高程")
        self.assertIn('"底高"', match)
        self.assertIn('"高程"', match)

    def test_clause_number_quoted(self):
        match = _build_fts_match_query("第5.4.12条")
        self.assertIn('"5.4.12"', match)
        # 不应产生未加引号的点分编号（会触发 FTS 语法错误）
        self.assertNotIn(" OR 5.4.12", match)

    def test_empty_query(self):
        self.assertEqual(_build_fts_match_query(""), "")


class TestExtractClauseRefsStrict(unittest.TestCase):
    def test_context_gated_clause(self):
        self.assertEqual(extract_clause_refs_strict("第5.4.12条规定的富裕水深是多少"), ["5.4.12"])

    def test_measurement_not_extracted(self):
        self.assertEqual(extract_clause_refs_strict("允许停泊波高H4%为1.5m怎么取"), [])
        self.assertEqual(extract_clause_refs_strict("水深1.5m、流速2.0m/s"), [])

    def test_table_ref_normalized(self):
        self.assertEqual(extract_clause_refs_strict("表5.4.12-1中的系数"), ["5.4.12.1"])

    def test_appendix_ref(self):
        self.assertEqual(extract_clause_refs_strict("附录A.0.1 船型尺度"), ["A.0.1"])

    def test_bare_three_segment_dotted(self):
        self.assertEqual(extract_clause_refs_strict("按5.4.12.1款计算"), ["5.4.12.1"])

    def test_single_dot_requires_context(self):
        # 无上下文的单点分编号（可能是测量值）不应抽取
        self.assertEqual(extract_clause_refs_strict("取值3.5m是否合规"), [])


class TestClauseAndFtsStore(unittest.TestCase):
    def setUp(self):
        # Windows 下 WAL 模式的 SQLite 文件句柄释放有延迟，忽略清理期文件锁错误
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = Path(self._tmp.name) / "index.sqlite"
        self.store = CanonicalSQLiteStore(self.db_path)
        with self.store.connect() as conn:
            conn.executemany(
                """
                INSERT INTO canonical_blocks (
                    block_id, doc_id, page_idx, block_type, text, text_clean,
                    reading_order, section_path, clause_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("b1", "d1", 0, "content", "富裕水深应按下式计算", "富裕水深应按下式计算", 1, "5 通航 / 5.4", "5.4.12"),
                    ("b2", "d1", 0, "content", "通航水位的确定", "通航水位的确定", 2, "5 通航 / 5.4", "5.4.12.1"),
                    ("b3", "d1", 1, "content", "码头前沿底高程", "码头前沿底高程", 3, "5 通航 / 5.4", "5.4.13"),
                    ("b4", "d1", 2, "content", "总则以HHHHH", "总则其他内容", 4, "1 总则", "1.1"),
                ],
            )
            conn.executemany(
                """
                INSERT INTO canonical_chunks (
                    chunk_id, doc_id, chunk_type, text, text_clean, token_count,
                    section_path, page_start, page_end
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    ("c1", "d1", "content", "码头前沿底高程计算", "码头前沿底高程计算", 8, "5 通航", 0, 0),
                    ("c2", "d1", "content", "允许停泊波高限值", "允许停泊波高限值", 8, "5 通航", 1, 1),
                ],
            )
            conn.commit()
        # 触发 FTS 重建（走与入库相同的路径）
        self.store.rebuild_chunk_fts("d1")

    def tearDown(self):
        self._tmp.cleanup()

    def test_clause_exact_and_hierarchy(self):
        hits = self.store.list_blocks_by_clause_refs("d1", ["5.4.12"], limit=10)
        clause_ids = {h["clause_id"] for h in hits}
        # 5.4.12 精确命中 + 5.4.12.1 子条款命中；5.4.13 同级不命中；1.1 无关不命中
        self.assertIn("5.4.12", clause_ids)
        self.assertIn("5.4.12.1", clause_ids)
        self.assertNotIn("5.4.13", clause_ids)
        self.assertNotIn("1.1", clause_ids)

    def test_clause_ancestor_match(self):
        # 查询更细的编号，应命中其父级 block
        hits = self.store.list_blocks_by_clause_refs("d1", ["5.4.12.1"], limit=10)
        clause_ids = {h["clause_id"] for h in hits}
        self.assertIn("5.4.12.1", clause_ids)
        self.assertIn("5.4.12", clause_ids)

    def test_fts_two_char_cjk(self):
        hits = self.store.search_chunk_fts("d1", "波高", limit=5)
        self.assertTrue(any(h["chunk_id"] == "c2" for h in hits))

    def test_fts_three_char_cjk(self):
        hits = self.store.search_chunk_fts("d1", "底高程", limit=5)
        self.assertTrue(any(h["chunk_id"] == "c1" for h in hits))

    def test_fts_no_false_hit(self):
        hits = self.store.search_chunk_fts("d1", "防波堤", limit=5)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
