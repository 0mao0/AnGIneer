# -*- coding: utf-8 -*-
"""解析记录流水（parse_records）的写入路径单测。

背景（2026-09-14 实踩）：这张表以前只由 docs-api 注入的 record_updater 写，
脚本/进程内路径（语料导入、评测 in-process）没有注入 → 文档只进 nodes 不进流水，
管理端「日常维护」整篇看不见（盘上 295 篇有 189 篇不在流水）。
现在默认实现下沉到 docs_core.parse_records_store，所有路径统一。
"""
import importlib
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-api"))

from docs_core import parse_records_store as store   # noqa: E402

_FAKE_META = {"library_id": "lib-x", "file_name": "a.pdf", "file_format": "pdf", "file_size": 12}


class ParseRecordsStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["PARSE_RECORDS_DB_PATH"] = str(Path(self.tmp.name) / "parse_records.sqlite")
        self._orig_meta = store._document_meta
        store._document_meta = lambda doc_id: dict(_FAKE_META)

    def tearDown(self):
        store._document_meta = self._orig_meta
        os.environ.pop("PARSE_RECORDS_DB_PATH", None)
        self.tmp.cleanup()

    def _rows(self):
        if not os.path.exists(store.db_path()):
            return []
        conn = sqlite3.connect(store.db_path())
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute("SELECT * FROM parse_records ORDER BY id")]
        except sqlite3.OperationalError:
            return []
        finally:
            conn.close()

    def test_creates_record_when_none_exists(self):
        """脚本/进程内路径第一次解析：没有占位记录，也要落一条（带文件元信息与来源）。"""
        store.sync_record_for_task("parse-abc", "doc-1", "processing", actor="system:corpus-import")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["doc_id"], "doc-1")
        self.assertEqual(rows[0]["task_id"], "parse-abc")
        self.assertEqual(rows[0]["status"], "processing")
        self.assertEqual(rows[0]["library_id"], "lib-x")
        self.assertEqual(rows[0]["file_name"], "a.pdf")
        self.assertEqual(rows[0]["file_format"], "pdf")
        self.assertEqual(rows[0]["file_size"], 12)
        self.assertEqual(rows[0]["uploaded_by"], "system:corpus-import")

    def test_renames_pending_placeholder(self):
        """界面/API 先写 pending-<doc_id> 占位，解析开始后改名成真实 task_id（原语义保留）。"""
        store.insert_record(doc_id="doc-1", task_id="pending-doc-1", uploaded_by="管理员", status="pending")
        store.sync_record_for_task("parse-abc", "doc-1", "processing")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_id"], "parse-abc")
        self.assertEqual(rows[0]["status"], "processing")

    def test_reuses_latest_record_of_same_doc(self):
        """重新解析同一篇：复用最新那条，不新增行、不把 created_at 顶到最新。"""
        store.insert_record(doc_id="doc-1", task_id="parse-old", status="completed", created_at="2026-01-01T00:00:00+00:00")
        store.sync_record_for_task("parse-new", "doc-1", "processing")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["task_id"], "parse-new")
        self.assertEqual(rows[0]["created_at"], "2026-01-01T00:00:00+00:00")

    def test_syncs_terminal_status(self):
        store.insert_record(doc_id="doc-1", task_id="parse-abc", status="processing")
        store.sync_record_for_task("parse-abc", "doc-1", "failed", "MinerU 超时")
        row = self._rows()[0]
        self.assertEqual(row["status"], "failed")
        self.assertEqual(row["error"], "MinerU 超时")

    def test_orchestrator_default_writes_record(self):
        """ParseOrchestrator 不注入钩子时也要写流水（本次修复的核心）。"""
        from docs_core.parse_pipeline import ParseOrchestrator

        orchestrator = ParseOrchestrator(record_actor="system:unit-test")
        self.assertIsNotNone(orchestrator._record_updater)
        orchestrator._sync_record("parse-def", "doc-9", "processing")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["uploaded_by"], "system:unit-test")

    def test_injected_updater_still_wins(self):
        """API 层注入自己的实现时，默认实现不参与（保持界面语义）。"""
        from docs_core.parse_pipeline import ParseOrchestrator

        seen = []
        orchestrator = ParseOrchestrator(record_updater=lambda *a: seen.append(a))
        orchestrator._sync_record("parse-x", "doc-1", "processing")
        self.assertEqual(seen, [("parse-x", "doc-1", "processing", None)])
        self.assertEqual(self._rows(), [])

    def test_schema_single_source_with_docs_api(self):
        """docs-api 的 init_db 与 docs-core 的 init_schema 必须产生同一套列（防两处 DDL 漂移）。"""
        store_conn = store.connect()
        try:
            store.init_schema(store_conn)
            store_columns = {r[1] for r in store_conn.execute("PRAGMA table_info(parse_records)")}
        finally:
            store_conn.close()

        # docs-api 侧另开一个空库（不删在用文件：Windows 上 WAL 会锁住句柄）
        api_db = str(Path(self.tmp.name) / "api_side.sqlite")
        os.environ["PARSE_RECORDS_DB_PATH"] = api_db
        api = importlib.import_module("models.parse_record")
        importlib.reload(api)
        api.init_db()
        conn = sqlite3.connect(api_db)
        try:
            api_columns = {r[1] for r in conn.execute("PRAGMA table_info(parse_records)")}
        finally:
            conn.close()
        self.assertEqual(store_columns, api_columns)


if __name__ == "__main__":
    unittest.main()
