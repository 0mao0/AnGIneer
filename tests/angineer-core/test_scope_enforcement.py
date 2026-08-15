"""阶段 2c 测试：检索链路 scope 强校验（entity_search 缺 scope 报错、结果带 scope）。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.agent_tools import RetrieverAdapter  # noqa: E402


class EntitySearchScopeTests(unittest.TestCase):
    def test_missing_library_id_raises(self):
        """缺 scope 直接报错，不允许默认猜 default。"""
        with self.assertRaises(TypeError):
            RetrieverAdapter.entity_search()

    def test_result_carries_scope(self):
        entity = Mock()
        entity.model_dump.return_value = {"name": "e1", "layer": "concept"}

        tool = RetrieverAdapter.entity_search(library_id="lib-x", doc_ids=["d1"])
        with patch("docs_core.step07_graph.graph_store.GraphStore") as store_cls:
            store_cls.return_value.search_entities.return_value = [entity]
            result = tool.handler(query="系缆力")

        self.assertEqual(result["scope"]["library_id"], "lib-x")
        self.assertEqual(result["scope"]["doc_ids"], ["d1"])
        self.assertEqual(result["total"], 1)

    def test_fallback_search_receives_scope(self):
        tool = RetrieverAdapter.entity_search(library_id="lib-y", doc_ids=["d2"])
        with patch("docs_core.step07_graph.graph_store.GraphStore") as store_cls, \
             patch("angineer_core.agent_tools._run_knowledge_search", return_value={"items": [], "citations": []}) as fallback:
            store_cls.return_value.search_entities.return_value = []
            result = tool.handler(query="查无此实体")

        self.assertEqual(fallback.call_args.kwargs["library_id"], "lib-y")
        self.assertEqual(fallback.call_args.kwargs["doc_ids"], ["d2"])
        self.assertEqual(result["scope"]["library_id"], "lib-y")


if __name__ == "__main__":
    unittest.main()
