# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from docs_core.step05_sqlite_fts.store.blocks_sql_store import KnowledgeMetaStore


class TestParseStagesStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.store = KnowledgeMetaStore(Path(self._tmp.name) / "meta.sqlite")

    def tearDown(self):
        self._tmp.cleanup()

    def test_upsert_and_list_stages(self):
        self.store.upsert_parse_stage("doc1", "raw_parse", status="completed", message="ok")
        self.store.upsert_parse_stage("doc1", "vectors", status="failed", error="embedding down")
        stages = self.store.list_parse_stages("doc1")
        by_name = {s["stage"]: s for s in stages}
        self.assertEqual(by_name["raw_parse"]["status"], "completed")
        self.assertEqual(by_name["vectors"]["status"], "failed")
        self.assertIn("embedding down", by_name["vectors"]["error"])

    def test_upsert_overwrites_same_stage(self):
        self.store.upsert_parse_stage("doc1", "vectors", status="failed", error="e1")
        self.store.upsert_parse_stage("doc1", "vectors", status="completed")
        stages = self.store.list_parse_stages("doc1")
        self.assertEqual(len(stages), 1)
        self.assertEqual(stages[0]["status"], "completed")
        self.assertEqual(stages[0]["error"], "")

    def test_clear_parse_stages(self):
        self.store.upsert_parse_stage("doc1", "vectors", status="failed", error="e1")
        self.store.clear_parse_stages("doc1")
        self.assertEqual(self.store.list_parse_stages("doc1"), [])

    def test_page_counts_by_doc_ids(self):
        self.store.upsert_parse_stage("doc1", "raw_parse", status="completed", message="ok", page_count=465)
        self.store.upsert_parse_stage("doc1", "vectors", status="completed")
        self.store.upsert_parse_stage("doc2", "raw_parse", status="completed", page_count=12)
        # structure 阶段的 page_count 不应被统计（仅 raw_parse 落库页数）
        self.store.upsert_parse_stage("doc3", "structure", status="completed", page_count=99)
        counts = self.store.page_counts_by_doc_ids(["doc1", "doc2", "doc3", "missing"])
        self.assertEqual(counts, {"doc1": 465, "doc2": 12})

    def test_page_counts_by_doc_ids_empty(self):
        self.assertEqual(self.store.page_counts_by_doc_ids([]), {})


if __name__ == "__main__":
    unittest.main()
