"""阶段 2b 测试：v1 文档 API 显式 library_id——默认 default，可显式传入并记录到 parse record。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

import models.parse_record as parse_record  # noqa: E402
from models.parse_record import ParseRecord  # noqa: E402


class ParseRecordLibraryIdTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = self._make_tmp()
        self.addCleanup(self._cleanup_tmp)

    def _make_tmp(self):
        import tempfile

        return tempfile.mkdtemp()

    def _cleanup_tmp(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _use_tmp_db(self):
        db_path = os.path.join(self.tmp_dir, "parse_records.sqlite")
        return patch.object(parse_record, "DB_PATH", db_path)

    def test_record_defaults_to_default_library(self):
        record = ParseRecord(doc_id="d1", task_id="t1")
        self.assertEqual(record.library_id, "default")

    def test_insert_and_list_roundtrip_keeps_library_id(self):
        with self._use_tmp_db():
            parse_record.insert_record(ParseRecord(doc_id="d1", task_id="t1", library_id="lib-x"))
            parse_record.insert_record(ParseRecord(doc_id="d2", task_id="t2"))
            rows = {r["doc_id"]: r for r in parse_record.list_records()}
        self.assertEqual(rows["d1"]["library_id"], "lib-x")
        self.assertEqual(rows["d2"]["library_id"], "default")

    def test_init_db_migrates_legacy_table_without_library_id(self):
        import sqlite3

        with self._use_tmp_db():
            conn = sqlite3.connect(parse_record.DB_PATH)
            conn.execute(
                """CREATE TABLE parse_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    uploaded_by TEXT NOT NULL DEFAULT '', api_key_id INTEGER,
                    file_name TEXT NOT NULL DEFAULT '', file_format TEXT NOT NULL DEFAULT '',
                    file_size INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT, created_at TEXT NOT NULL
                )"""
            )
            conn.execute("INSERT INTO parse_records (doc_id, task_id, created_at) VALUES ('old', 't0', '2024-01-01')")
            conn.commit()
            conn.close()

            parse_record.init_db()
            rows = parse_record.list_records()
        self.assertEqual(rows[0]["library_id"], "default")

    def test_record_defaults_to_empty_stages(self):
        record = ParseRecord(doc_id="d1", task_id="t1")
        self.assertEqual(record.stages, "")

    def test_insert_and_list_roundtrip_keeps_stages(self):
        with self._use_tmp_db():
            parse_record.insert_record(ParseRecord(doc_id="d1", task_id="t1", stages="structure,fts"))
            rows = {r["doc_id"]: r for r in parse_record.list_records()}
        self.assertEqual(rows["d1"]["stages"], "structure,fts")

    def test_init_db_migrates_legacy_table_without_stages(self):
        import sqlite3

        with self._use_tmp_db():
            conn = sqlite3.connect(parse_record.DB_PATH)
            conn.execute(
                """CREATE TABLE parse_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    doc_id TEXT NOT NULL, task_id TEXT NOT NULL,
                    uploaded_by TEXT NOT NULL DEFAULT '', api_key_id INTEGER,
                    file_name TEXT NOT NULL DEFAULT '', file_format TEXT NOT NULL DEFAULT '',
                    file_size INTEGER NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'queued',
                    error TEXT, created_at TEXT NOT NULL,
                    library_id TEXT NOT NULL DEFAULT 'default'
                )"""
            )
            conn.execute("INSERT INTO parse_records (doc_id, task_id, created_at) VALUES ('old', 't0', '2024-01-01')")
            conn.commit()
            conn.close()

            parse_record.init_db()
            rows = parse_record.list_records()
        self.assertEqual(rows[0]["stages"], "")


class V1DocumentsScopeTests(unittest.TestCase):
    """/parse 显式传入并记录；只读端点从 record 反查 library_id。"""

    def _make_client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        import routes.v1.documents as documents

        app = FastAPI()
        app.include_router(documents.router, prefix="/api/v1/documents")
        return documents, TestClient(app)

    def _parse_mocks(self, documents):
        docs_service = Mock()
        docs_service.nodes = []
        docs_service.create_node.return_value = Mock(id="folder-1")
        return (
            patch.object(documents.file_storage, "save_source_file", return_value="src/f.md"),
            patch.object(documents, "get_docs_service", return_value=docs_service),
            patch.object(documents.parse_orchestrator, "create_parse_task", return_value={"task_id": "t-1", "status": "queued"}),
        )

    def test_parse_accepts_explicit_library_id_and_records_it(self):
        documents, client = self._make_client()
        save_mock, svc_mock, task_mock = self._parse_mocks(documents)
        inserted = []

        with self._tmp_db(), save_mock as save_file, svc_mock, task_mock as create_task, \
             patch.object(documents, "insert_record", side_effect=inserted.append):
            docs_service = documents.get_docs_service.return_value
            resp = client.post(
                "/api/v1/documents/parse?library_id=lib-x",
                files={"file": ("a.md", b"# hello", "text/markdown")},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(save_file.call_args.args[0], "lib-x")
        self.assertEqual(create_task.call_args.kwargs["library_id"], "lib-x")
        self.assertEqual(inserted[0].library_id, "lib-x")
        docs_service.register_document.assert_called_once()

    def test_parse_defaults_to_default_library(self):
        documents, client = self._make_client()
        save_mock, svc_mock, task_mock = self._parse_mocks(documents)
        inserted = []

        with self._tmp_db(), save_mock as save_file, svc_mock, task_mock as create_task, \
             patch.object(documents, "insert_record", side_effect=inserted.append):
            resp = client.post(
                "/api/v1/documents/parse",
                files={"file": ("a.md", b"# hello", "text/markdown")},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(save_file.call_args.args[0], "default")
        self.assertEqual(create_task.call_args.kwargs["library_id"], "default")
        self.assertEqual(inserted[0].library_id, "default")
        self.assertEqual(inserted[0].stages, "structure")

    def test_status_resolves_library_from_record(self):
        documents, client = self._make_client()
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(doc_id="d1", task_id="t-1", library_id="lib-x", file_format=".md"))
            with patch.object(documents.parse_orchestrator, "get_parse_task", return_value=None), \
                 patch.object(documents.file_storage, "get_doc_manifest", return_value={}) as manifest_mock:
                resp = client.get("/api/v1/documents/d1/status")

        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(manifest_mock.call_args.args[0], "lib-x")

    def test_status_falls_back_to_default_without_record(self):
        documents, client = self._make_client()
        with self._tmp_db():
            with patch.object(documents.parse_orchestrator, "get_parse_task", return_value=None), \
                 patch.object(documents.file_storage, "get_doc_manifest", return_value={}):
                resp = client.get("/api/v1/documents/ghost/status")

        self.assertEqual(resp.status_code, 404)

    def test_parse_creates_folder_named_after_api_key_in_bound_library(self):
        from types import SimpleNamespace
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import routes.v1.documents as documents

        app = FastAPI()

        @app.middleware("http")
        async def _fake_key(request, call_next):
            request.state.api_key_info = SimpleNamespace(
                user_name="bidcompare", id=5, library_id="lib-bidcompare"
            )
            return await call_next(request)

        app.include_router(documents.router, prefix="/api/v1/documents")
        client = TestClient(app)
        save_mock, svc_mock, task_mock = self._parse_mocks(documents)
        inserted = []

        with self._tmp_db(), save_mock as save_file, svc_mock, task_mock, \
             patch.object(documents, "insert_record", side_effect=inserted.append):
            docs_service = documents.get_docs_service.return_value
            resp = client.post(
                "/api/v1/documents/parse?library_id=default",
                files={"file": ("a.md", b"# hello", "text/markdown")},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        # 目标库优先取 API key 绑定的库，而不是请求参数
        self.assertEqual(save_file.call_args.args[0], "lib-bidcompare")
        # 根文件夹以 API 名称命名，文档挂在它下面
        created = docs_service.create_node.call_args.args[0]
        self.assertEqual(created.title, "bidcompare")
        self.assertEqual(created.library_id, "lib-bidcompare")
        self.assertIsNone(created.parent_id)
        docs_service.register_document.assert_called_once()
        self.assertEqual(docs_service.register_document.call_args.kwargs["parent_id"], "folder-1")

    def test_parse_without_api_key_uses_fallback_folder_name(self):
        documents, client = self._make_client()
        save_mock, svc_mock, task_mock = self._parse_mocks(documents)
        inserted = []

        with self._tmp_db(), save_mock, svc_mock, task_mock, \
             patch.object(documents, "insert_record", side_effect=inserted.append):
            docs_service = documents.get_docs_service.return_value
            resp = client.post(
                "/api/v1/documents/parse",
                files={"file": ("a.md", b"# hello", "text/markdown")},
            )

        self.assertEqual(resp.status_code, 200, resp.text)
        created = docs_service.create_node.call_args.args[0]
        self.assertEqual(created.title, "未知API")

    def _tmp_db(self):
        import tempfile

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        return patch.object(parse_record, "DB_PATH", os.path.join(tmp_dir, "parse_records.sqlite"))


if __name__ == "__main__":
    unittest.main()
