# -*- coding: utf-8 -*-
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

import startup_recovery


class ReconcileStaleParseTasksTests(unittest.TestCase):
    def _task(self, task_id="t1", doc_id="d1", status="processing"):
        task = Mock()
        task.id = task_id
        task.doc_id = doc_id
        task.status = status
        return task

    def test_marks_processing_as_failed_and_syncs(self):
        ks = Mock()
        ks.parse_tasks = [self._task(), self._task("t2", "d2", status="completed")]
        orch = Mock()
        orch._threads = {}
        expected_error = startup_recovery.INTERRUPTED_ERROR.format(doc_id="d1")

        with patch.object(startup_recovery, "update_record_status") as upd:
            count = startup_recovery.reconcile_stale_parse_tasks(orch, docs_service=ks)

        self.assertEqual(count, 1)
        ks.update_parse_task.assert_called_once_with(
            "t1", status="failed", progress=100, stage="failed",
            stage_message=expected_error, error=expected_error,
        )
        ks.update_node.assert_called_once_with(
            "d1", status="failed", parse_progress=100, parse_stage="failed",
            parse_error=expected_error,
        )
        upd.assert_called_once_with("t1", "failed", expected_error)

    def test_skips_task_with_live_thread(self):
        ks = Mock()
        ks.parse_tasks = [self._task()]
        thread = Mock()
        thread.is_alive.return_value = True
        orch = Mock()
        orch._threads = {"t1": thread}

        count = startup_recovery.reconcile_stale_parse_tasks(orch, docs_service=ks)

        self.assertEqual(count, 0)
        ks.update_parse_task.assert_not_called()
        ks.update_node.assert_not_called()


if __name__ == "__main__":
    unittest.main()
