"""阶段 5：Dispatcher 清退边界测试——主链路只认 SopRunner，工牌收回。"""
import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))


class DispatcherRetirementTests(unittest.TestCase):
    def test_core_no_longer_exports_dispatcher(self):
        import angineer_core

        self.assertFalse(hasattr(angineer_core, "Dispatcher"))

    def test_dispatcher_module_removed(self):
        sys.modules.pop("angineer_core.dispatcher", None)
        with self.assertRaises(ModuleNotFoundError):
            importlib.import_module("angineer_core.dispatcher")

    def test_config_exposes_runner_not_dispatcher(self):
        from angineer_core.base_config import AnGIneerConfig, RunnerConfig

        config = AnGIneerConfig()
        self.assertIsInstance(config.runner, RunnerConfig)
        self.assertFalse(hasattr(config, "dispatcher"))

    def test_runner_config_reads_reranker_configs(self):
        from angineer_core import base_config

        env = {
            "RERANKER_CONFIGS": (
                '[{"name":"primary","url":"http://rerank:9000","api_key":"k1",'
                '"timeout_sec":5.5},{"name":"backup","url":"http://rerank2:9000"}]'
            )
        }
        with patch.dict(os.environ, env):
            config = base_config.load_config_from_env()
        self.assertEqual(config.runner.reranker_url, "http://rerank:9000")
        self.assertEqual(len(config.runner.reranker_configs), 2)
        self.assertEqual(config.runner.reranker_configs[0]["name"], "primary")
        self.assertEqual(config.runner.reranker_timeout_sec, 10.0)  # 默认（未设 ANGINEER_RERANKER_TIMEOUT_SEC）

    def test_rerank_candidates_consumes_runner_config(self):
        """retrieval_pipeline 重排配置读取入口从 .dispatcher 切到 .runner。"""
        import inspect

        from angineer_core import retrieval_pipeline

        source = inspect.getsource(retrieval_pipeline.rerank_candidates)
        self.assertIn(".runner", source)
        self.assertNotIn(".dispatcher", source)


if __name__ == "__main__":
    unittest.main()
