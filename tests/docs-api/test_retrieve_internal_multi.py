"""docs-api /api/knowledge/internal/retrieve 多库透传（阶段三 A6）。

sys.path 注入照搬 tests/aichat-api/test_chat_auth_scope.py 惯例；
路由实名 retrieve_router、测试 app 挂 main.py 同款前缀 /api/knowledge。
"""
import os
import sys
import unittest
from unittest.mock import patch

_DOCS_API_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api"))
sys.path.append(_DOCS_API_DIR)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from retrieve_routes import retrieve_router


class TestRetrieveInternalMultiLibrary(unittest.TestCase):
    def _client(self):
        app = FastAPI()
        app.include_router(retrieve_router, prefix="/api/knowledge")
        return TestClient(app)

    def test_library_ids_passed_to_retrieve_knowledge(self):
        with patch("retrieve_routes.retrieve_knowledge", return_value={"items": [], "total": 0}) as mock_ret:
            client = self._client()
            resp = client.post("/api/knowledge/internal/retrieve", json={
                "query": "混凝土", "library_ids": ["libA", "libB"], "top_k": 20,
            })
            self.assertEqual(resp.status_code, 200)
            kwargs = mock_ret.call_args.kwargs
            self.assertEqual(kwargs.get("library_ids"), ["libA", "libB"])

    def test_legacy_single_library_body_still_works(self):
        with patch("retrieve_routes.retrieve_knowledge", return_value={"items": [], "total": 0}) as mock_ret:
            client = self._client()
            resp = client.post("/api/knowledge/internal/retrieve", json={
                "query": "混凝土", "library_id": "libA", "top_k": 20,
            })
            self.assertEqual(resp.status_code, 200)
            kwargs = mock_ret.call_args.kwargs
            self.assertIn(kwargs.get("library_ids"), (None, []))
            self.assertEqual(kwargs.get("library_id"), "libA")


if __name__ == "__main__":
    unittest.main()
