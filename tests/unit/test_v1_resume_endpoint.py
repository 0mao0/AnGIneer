# -*- coding: utf-8 -*-
import os
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

import models.parse_record as parse_record
from models.parse_record import ParseRecord


class V1ResumeEndpointTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.addCleanup(self._cleanup_tmp)

    def _cleanup_tmp(self):
        import shutil

        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _tmp_db(self):
        return patch.object(parse_record, "DB_PATH", os.path.join(self.tmp_dir, "parse_records.sqlite"))

    def _make_client(self, key_id=5, bound_library=""):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        import routes.v1.documents as documents

        key = Mock()
        key.id = key_id
        key.library_id = bound_library

        app = FastAPI()

        @app.middleware("http")
        async def fake_auth(request, call_next):
            request.state.api_key_info = key
            return await call_next(request)

        app.include_router(documents.router, prefix="/api/v1/documents")
        return documents, TestClient(app)

    def _node(self, doc_id="d1", file_path="src/f.pdf", deleted=False):
        node = Mock()
        node.id = doc_id
        node.file_path = file_path
        node.deleted = deleted
        node.library_id = "default"
        return node

    def _rows(self):
        return [
            {"stage": "source_prep", "status": "completed"},
            {"stage": "convert", "status": "skipped"},
            {"stage": "raw_parse", "status": "completed"},
            {"stage": "popo", "status": "running"},
        ]

    def test_resume_rejects_other_keys_document(self):
        documents, client = self._make_client(key_id=6)
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(
                doc_id="d1", task_id="t1", api_key_id=5, library_id="default",
                file_format=".pdf", stages="structure", status="processing",
            ))
            with patch.object(documents, "get_docs_service") as g:
                ks = Mock()
                ks.get_node.return_value = self._node()
                g.return_value = ks
                resp = client.post("/api/v1/documents/d1/resume")
        self.assertEqual(resp.status_code, 403, resp.text)

    def test_resume_404_when_node_missing(self):
        documents, client = self._make_client()
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(
                doc_id="d1", task_id="t1", api_key_id=5, library_id="default",
                file_format=".pdf", stages="structure", status="processing",
            ))
            with patch.object(documents, "get_docs_service") as g:
                ks = Mock()
                ks.get_node.return_value = None
                g.return_value = ks
                resp = client.post("/api/v1/documents/d1/resume")
        self.assertEqual(resp.status_code, 404, resp.text)

    def test_resume_409_when_task_thread_alive(self):
        documents, client = self._make_client()
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(
                doc_id="d1", task_id="t1", api_key_id=5, library_id="default",
                file_format=".pdf", stages="structure", status="processing",
            ))
            with patch.object(documents, "get_docs_service") as g, \
                 patch.object(documents.parse_orchestrator, "create_parse_task") as create:
                ks = Mock()
                ks.get_node.return_value = self._node()
                g.return_value = ks
                thread = Mock()
                thread.is_alive.return_value = True
                documents.parse_orchestrator._threads = {"t1": thread}
                resp = client.post("/api/v1/documents/d1/resume")
        self.assertEqual(resp.status_code, 409, resp.text)
        create.assert_not_called()
        documents.parse_orchestrator._threads = {}

    def test_resume_creates_new_task_for_stale_processing(self):
        documents, client = self._make_client()
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(
                doc_id="d1", task_id="t1", api_key_id=5, library_id="default",
                file_format=".pdf", stages="all", status="processing",
            ))
            with patch.object(documents, "get_docs_service") as g, \
                 patch.object(documents.parse_orchestrator, "cancel_parse_task") as cancel, \
                 patch.object(documents.parse_orchestrator, "create_parse_task",
                              return_value={"task_id": "t2", "status": "processing"}) as create:
                ks = Mock()
                ks.get_node.return_value = self._node()
                ks.meta_store.list_parse_stages.return_value = self._rows()
                g.return_value = ks
                documents.parse_orchestrator._threads = {}
                resp = client.post("/api/v1/documents/d1/resume")
        self.assertEqual(resp.status_code, 200, resp.text)
        payload = resp.json()
        self.assertEqual(payload["task_id"], "t2")
        self.assertEqual(payload["status"], "processing")
        self.assertTrue(payload["is_pdf_input"])
        cancel.assert_called_once_with("t1")
        create.assert_called_once()
        self.assertEqual(
            create.call_args.kwargs["parse_options"]["stages"],
            ["popo", "structure", "fts", "vectors", "graph"],
        )
        documents.parse_orchestrator._threads = {}

    def test_resume_noop_when_all_stages_done(self):
        documents, client = self._make_client()
        with self._tmp_db():
            parse_record.insert_record(ParseRecord(
                doc_id="d1", task_id="t1", api_key_id=5, library_id="default",
                file_format=".pdf", stages="all", status="completed",
            ))
            with patch.object(documents, "get_docs_service") as g, \
                 patch.object(documents.parse_orchestrator, "cancel_parse_task"), \
                 patch.object(documents.parse_orchestrator, "create_parse_task") as create:
                ks = Mock()
                ks.get_node.return_value = self._node()
                ks.meta_store.list_parse_stages.return_value = [
                    {"stage": s, "status": "completed"}
                    for s in ("source_prep", "convert", "raw_parse", "popo", "structure", "fts", "vectors", "graph")
                ]
                g.return_value = ks
                documents.parse_orchestrator._threads = {}
                resp = client.post("/api/v1/documents/d1/resume")
        self.assertEqual(resp.status_code, 200, resp.text)
        self.assertEqual(resp.json()["status"], "completed")
        create.assert_not_called()
        documents.parse_orchestrator._threads = {}


if __name__ == "__main__":
    unittest.main()
