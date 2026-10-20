"""docs-api /api/knowledge/internal/doc-search 时间维度参数透传（2026-10-20）。"""
import os
import sys
import unittest
from unittest.mock import patch

_REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
sys.path.append(os.path.join(_REPO, "services/docs-api"))
sys.path.append(os.path.join(_REPO, "services/docs-core/src"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from retrieve_routes import retrieve_router  # noqa: E402
from docs_core.step09_query import doc_search as doc_search_module  # noqa: E402


class TestDocSearchTimeParams(unittest.TestCase):
    def _post(self, payload):
        app = FastAPI()
        app.include_router(retrieve_router, prefix="/api/knowledge")
        return TestClient(app).post("/api/knowledge/internal/doc-search", json=payload)

    def test_date_params_forwarded(self):
        with patch.object(doc_search_module, "search_documents", return_value={"matters": []}) as mock_search:
            resp = self._post({
                "query": "credit agreement",
                "sort_by": "date_desc",
                "date_after": "2024-01-01",
                "date_before": "2024-12-31",
            })
            self.assertEqual(resp.status_code, 200)
            kwargs = mock_search.call_args.kwargs
            self.assertEqual(kwargs.get("sort_by"), "date_desc")
            self.assertEqual(kwargs.get("date_after"), "2024-01-01")
            self.assertEqual(kwargs.get("date_before"), "2024-12-31")

    def test_legacy_body_without_date_params_keeps_old_call(self):
        with patch.object(doc_search_module, "search_documents", return_value={"matters": []}) as mock_search:
            resp = self._post({"query": "credit agreement", "library_id": "libA"})
            self.assertEqual(resp.status_code, 200)
            kwargs = mock_search.call_args.kwargs
            # 不传日期 → None（search_documents 侧走旧的相关性排序）
            self.assertIsNone(kwargs.get("sort_by"))
            self.assertIsNone(kwargs.get("date_after"))
            self.assertIsNone(kwargs.get("date_before"))


if __name__ == "__main__":
    unittest.main()
