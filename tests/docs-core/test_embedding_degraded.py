"""回归测试：embedding hash 降级在解析完成时浮现到任务消息与记录（不再只埋阶段日志）。"""
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core import parse_pipeline as pp  # noqa: E402


class EmbeddingDegradedSurfacingTests(unittest.TestCase):
    def _run_task(self, runtime_flags):
        ks = MagicMock()
        ks.meta_store = MagicMock()
        ks.get_node.return_value = MagicMock(file_path="a.docx")
        ks.list_parse_stages = MagicMock(return_value=[])

        with patch.object(pp, "_MINERU_GPU_GATE", pp._FifoGpuGate(1)), \
             patch.object(pp, "get_docs_service", return_value=ks), \
             patch.object(pp, "run_pipeline", return_value={"source_prep": "completed"}), \
             patch("docs_core.step06_vectors.embedding_provider.default_embedding_provider") as mock_provider:
            mock_provider.runtime_flags = runtime_flags
            orch = pp.ParseOrchestrator()
            sync_calls = []
            orch._sync_record = lambda *args: sync_calls.append(args)
            orch._run_parse_task("task-e", "lib", "doc-e", "a.docx", {"stages": ["source_prep"]}, arrival_seq=1)

        update_kwargs = ks.update_parse_task.call_args.kwargs
        return update_kwargs, sync_calls

    def test_completion_message_marks_hash_fallback(self):
        update_kwargs, sync_calls = self._run_task(["embedding_hash_fallback"])
        self.assertIn("hash", update_kwargs["stage_message"])
        self.assertTrue(any(call[3] for call in sync_calls if len(call) >= 4 and call[3]))

    def test_completion_message_clean_when_no_fallback(self):
        update_kwargs, sync_calls = self._run_task([])
        self.assertNotIn("hash", update_kwargs["stage_message"])
        self.assertTrue(all(not (call[3] if len(call) >= 4 else None) for call in sync_calls))


if __name__ == "__main__":
    unittest.main()
