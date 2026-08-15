"""阶段 6 测试：run manifest 统一——build_run_manifest 脱敏快照 + eval_run.config_snapshot 落盘。"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.run_manifest import build_run_manifest  # noqa: E402


class BuildRunManifestTests(unittest.TestCase):
    def test_manifest_shape_and_sanitization(self):
        env = {
            "ANGINEER_DEFAULT_MODEL": "qwen-test",
            "ANGINEER_ROUTE_PRE": "true",
            "ANGINEER_DOCS_API_URL": "http://docs-api:8010",
            "DOCS_VECTORSTORE_PROVIDER": "sqlite",
            "OPENAI_API_KEY": "sk-should-not-appear",
        }
        with patch.dict(os.environ, env, clear=False):
            manifest = build_run_manifest()

        self.assertEqual(manifest["schema_version"], "eval.run_manifest.v1")
        self.assertIn("prompt_versions", manifest)
        self.assertIsInstance(manifest["prompt_versions"], dict)
        self.assertEqual(manifest["model"], "qwen-test")
        self.assertEqual(manifest["flags"]["route_pre"], "true")
        self.assertEqual(manifest["flags"]["docs_api_url"], "http://docs-api:8010")
        self.assertEqual(manifest["flags"]["vectorstore_provider"], "sqlite")
        self.assertIn("created_at", manifest)
        self.assertNotIn("sk-should-not-appear", str(manifest))


class EvalRunManifestStoreTests(unittest.TestCase):
    def test_create_run_persists_config_snapshot(self):
        import tempfile

        from evals_core.storage import result_store

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        db_path = os.path.join(tmp_dir, "evals.sqlite")

        with patch.object(result_store, "_DB_PATH", db_path):
            result_store._get_thread_local().conn = None
            result_store.init_db()
            manifest = {"schema_version": "eval.run_manifest.v1", "model": "m1"}
            run = result_store.create_run("ds-1", 3, config_snapshot=manifest)
            loaded = result_store.get_run(run["run_id"])

        self.assertEqual(loaded["config_snapshot"]["model"], "m1")
        self.assertEqual(loaded["config_snapshot"]["schema_version"], "eval.run_manifest.v1")


class SuiteRunnerManifestTests(unittest.TestCase):
    def test_start_eval_run_writes_manifest(self):
        import tempfile

        from evals_core.runner import suite_runner
        from evals_core.storage import result_store

        tmp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: __import__("shutil").rmtree(tmp_dir, ignore_errors=True))
        db_path = os.path.join(tmp_dir, "evals.sqlite")

        with patch.object(result_store, "_DB_PATH", db_path):
            result_store._get_thread_local().conn = None
            result_store.init_db()
            result_store.insert_dataset({"dataset_id": "ds-1", "title": "t"})
            result_store.insert_question({
                "question_id": "q1", "dataset_id": "ds-1", "question": "测试",
            })
            with patch.object(suite_runner, "_run_suite_thread"):
                run = suite_runner.start_eval_run("ds-1")
            loaded = result_store.get_run(run["run_id"])

        snapshot = loaded["config_snapshot"]
        self.assertIsNotNone(snapshot)
        self.assertEqual(snapshot["schema_version"], "eval.run_manifest.v1")
        self.assertIn("prompt_versions", snapshot)


if __name__ == "__main__":
    unittest.main()
