"""回归测试：ParseOrchestrator 进程级单例——docs_routes 与 v1 路由必须共享同一实例。

多实例曾导致 _parsers/_cancelled 各自独立（跨路径取消静默失效）
与 GPU 闸门序号冲突（seq 重号误报"排队期间被取消"）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-api")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/tree-core/src")))


class ParseOrchestratorSingletonTests(unittest.TestCase):
    def test_both_route_modules_share_one_instance(self):
        import docs_routes
        import routes.v1.documents as v1_documents

        self.assertIs(docs_routes.parse_orchestrator, v1_documents.parse_orchestrator)

    def test_singleton_module_is_source_of_truth(self):
        import docs_routes
        import orchestrator

        self.assertIs(docs_routes.parse_orchestrator, orchestrator.parse_orchestrator)


if __name__ == "__main__":
    unittest.main()
