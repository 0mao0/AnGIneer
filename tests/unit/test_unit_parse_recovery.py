"""重启自愈与重试：queued 僵尸任务也能被清理，processing 但线程已死的节点允许重新解析。"""
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-api"))
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from startup_recovery import reconcile_stale_parse_tasks  # noqa: E402
from docs_core.parse_pipeline import ParseOrchestrator  # noqa: E402


class StaleTaskReconcileTests(unittest.TestCase):
    def test_queued_stale_task_marked_failed(self):
        tasks = [SimpleNamespace(id="parse-1", doc_id="doc-1", status="queued")]
        calls = []

        class FakeKs:
            parse_tasks = tasks

            def update_parse_task(self, task_id, **kwargs):
                calls.append(("task", task_id, kwargs))

            def update_node(self, doc_id, **kwargs):
                calls.append(("node", doc_id, kwargs))

        orchestrator = SimpleNamespace(_threads={})
        with patch("startup_recovery.update_record_status") as mock_rec:
            count = reconcile_stale_parse_tasks(orchestrator, FakeKs())
        self.assertEqual(count, 1)
        self.assertEqual(calls[0], ("task", "parse-1", unittest.mock.ANY))
        self.assertEqual(calls[0][2]["status"], "failed")
        mock_rec.assert_called_once()

    def test_alive_thread_not_touched(self):
        tasks = [SimpleNamespace(id="parse-1", doc_id="doc-1", status="queued")]
        calls = []

        class FakeKs:
            parse_tasks = tasks

            def update_parse_task(self, **kwargs):
                calls.append(kwargs)

            def update_node(self, **kwargs):
                calls.append(kwargs)

        thread = SimpleNamespace(is_alive=lambda: True)
        orchestrator = SimpleNamespace(_threads={"parse-1": thread})
        with patch("startup_recovery.update_record_status") as mock_rec:
            count = reconcile_stale_parse_tasks(orchestrator, FakeKs())
        self.assertEqual(count, 0)
        self.assertEqual(calls, [])
        mock_rec.assert_not_called()


if __name__ == "__main__":
    unittest.main()
