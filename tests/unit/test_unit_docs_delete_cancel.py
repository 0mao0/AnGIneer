"""Delete/soft-delete document nodes must cancel still-running parse tasks."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-api"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "tree-core" / "src"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "angineer-core" / "src"))

from routes.v1.parse_task_cleanup import cancel_parse_task_for_node  # noqa: E402


class CancelParseTaskForNodeTest(unittest.TestCase):
    def test_cancels_when_node_has_parse_task(self):
        orchestrator = MagicMock()
        node = MagicMock(parse_task_id="parse-abc")
        cancel_parse_task_for_node(node, orchestrator)
        orchestrator.cancel_parse_task.assert_called_once_with("parse-abc")

    def test_no_cancel_when_node_has_no_task(self):
        orchestrator = MagicMock()
        node = MagicMock(parse_task_id=None)
        cancel_parse_task_for_node(node, orchestrator)
        orchestrator.cancel_parse_task.assert_not_called()

    def test_cancel_failure_is_swallowed(self):
        orchestrator = MagicMock()
        orchestrator.cancel_parse_task.side_effect = RuntimeError("boom")
        node = MagicMock(parse_task_id="parse-abc")
        cancel_parse_task_for_node(node, orchestrator)  # must not raise


class DocsRoutesCancelWiringTest(unittest.TestCase):
    def test_delete_knowledge_node_cancels_before_delete(self):
        import docs_routes

        with patch.object(docs_routes, "cancel_parse_task_for_node") as helper, \
                patch.object(
                    docs_routes,
                    "get_docs_service",
                    return_value=MagicMock(delete_node=MagicMock(return_value=True)),
                ), \
                patch.object(docs_routes, "soft_delete_record", return_value=True):
            result = docs_routes.delete_knowledge_node("n1")
        helper.assert_called_once()
        self.assertEqual(result["status"], "success")

    def test_soft_delete_knowledge_node_cancels(self):
        import docs_routes

        with patch.object(docs_routes, "cancel_parse_task_for_node") as helper, \
                patch.object(
                    docs_routes,
                    "get_docs_service",
                    return_value=MagicMock(soft_delete_node=MagicMock(return_value=True)),
                ), \
                patch.object(docs_routes, "soft_delete_record", return_value=True):
            result = docs_routes.soft_delete_knowledge_node("n1")
        helper.assert_called_once()
        self.assertEqual(result["status"], "success")


class V1DeleteCancelWiringTest(unittest.TestCase):
    def test_delete_document_v1_cancels_parse_task(self):
        import importlib
        parse_record_mod = importlib.import_module("models.parse_record")
        from routes.v1 import documents

        with patch.object(documents, "cancel_parse_task_for_node") as helper, \
                patch.object(documents, "get_docs_service") as get_ks, \
                patch.object(parse_record_mod, "soft_delete_record", return_value=True):
            get_ks.return_value = MagicMock()
            request = MagicMock()
            request.state.api_key_info = {"id": 1}
            asyncio.run(documents.delete_document_v1(request, "doc1"))
        helper.assert_called_once()


if __name__ == "__main__":
    unittest.main()
