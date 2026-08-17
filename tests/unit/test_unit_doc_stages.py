"""GET /api/knowledge/documents/{doc_id}/stages 页数/扫描件透出契约。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))

from docs_routes import get_document_stages  # noqa: E402


class DocStagesApiTests(unittest.TestCase):
    def test_stages_carry_page_count_and_is_scanned(self):
        node = Mock(id="doc1", library_id="lib1", file_path="")
        stage_row = {
            "doc_id": "doc1", "stage": "raw_parse", "status": "completed",
            "message": "", "error": "", "started_at": "2026-08-17T00:00:00",
            "finished_at": "2026-08-17T00:01:00", "updated_at": "",
            "input_summary": "", "output_summary": "",
            "fallback": "", "page_count": 36, "is_scanned": 1,
        }
        meta_store = Mock()
        meta_store.list_parse_stages.return_value = [stage_row]
        meta_store.list_parse_stage_steps.return_value = []
        ks = Mock()
        ks.get_node.return_value = node
        ks.meta_store = meta_store
        with patch("docs_routes.get_docs_service", return_value=ks), \
             patch("docs_routes._stage_output_files", return_value=None):
            payload = get_document_stages("doc1")
        raw = next(s for s in payload["stages"] if s["stage"] == "raw_parse")
        self.assertEqual(raw["page_count"], 36)
        self.assertEqual(raw["is_scanned"], 1)


if __name__ == "__main__":
    unittest.main()
