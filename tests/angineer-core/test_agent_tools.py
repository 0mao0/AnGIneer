"""P2 工具契约与适配器单测。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))

from engtools.BaseTool import BaseTool, ToolRegistry  # noqa: E402
from angineer_core import ports  # noqa: E402
from angineer_core.agent_tools import (  # noqa: E402
    EngtoolAdapter,
    RetrieverAdapter,
    SopRunnerAdapter,
    ToolResult,
)


class FakeEchoTool(BaseTool):
    name = "fake_echo_tool"
    description_zh = "测试回声工具"
    description_en = "Test echo tool"

    def run(self, **kwargs):
        return kwargs


class AgentToolContractTests(unittest.TestCase):
    def setUp(self):
        if ToolRegistry.get_tool("fake_echo_tool") is None:
            ToolRegistry.register(FakeEchoTool())
        # EngtoolAdapter 经 engtool_registry 端口消费注册表（Seam 4）
        ports.register_agent_search(engtool_registry=lambda: ToolRegistry)

    def tearDown(self):
        ports.register_agent_search(engtool_registry=None)

    def test_engtool_adapter_injects_config_and_mode(self):
        tool = EngtoolAdapter.from_registry(
            "fake_echo_tool",
            description="回声",
            parameters_schema={"type": "object", "properties": {"text": {"type": "string"}}},
            config_name="cfg-a",
            mode="instruct",
        )
        result = tool.handler(text="hi")
        self.assertEqual(result["text"], "hi")
        self.assertEqual(result["config_name"], "cfg-a")
        self.assertEqual(result["mode"], "instruct")

    def test_engtool_adapter_missing_tool_raises(self):
        tool = EngtoolAdapter.from_registry("no_such_tool", description="x")
        with self.assertRaises(Exception):
            tool.handler()

    def test_tool_result_defaults(self):
        result = ToolResult(call_id="c1", name="n", content="{}")
        self.assertFalse(result.is_error)
        self.assertFalse(result.terminate)
        self.assertEqual(result.raw, {})

    def test_adapters_importable_and_sop_runner_guards_missing_query(self):
        self.assertTrue(callable(RetrieverAdapter.knowledge_search))
        self.assertTrue(callable(RetrieverAdapter.table_search))
        self.assertTrue(callable(RetrieverAdapter.entity_search))
        sop_tool = SopRunnerAdapter.sop_execute()
        result = sop_tool.handler(sop_query="", args={})
        self.assertIn("error", result)

    def test_assign_cites_marker_consistent(self):
        """引用标记分配留引擎（_assign_cites）；引用挑选本体已随 Seam 4 搬到
        docs-core 适配器（relevant_citations 端口），其断言见
        services/docs-core/tests/test_agent_port.py。"""
        from angineer_core.agent_tools import MarkerAllocator, _assign_cites
        from docs_core.step09_query.protocols.contracts import RetrievedItem

        items = [
            RetrievedItem(item_id="a", entity_type="content", doc_id="d1", title="t1",
                          text="船闸规范 闸门有 4 个等级", score=1.0,
                          metadata={"doc_title": "船闸规范.pdf"}),
            RetrievedItem(item_id="b", entity_type="content", doc_id="d2", title="t2",
                          text="海港 航道 2 级", score=1.0,
                          metadata={"doc_title": "海港2.pdf"}),
        ]
        allocator = MarkerAllocator()
        _assign_cites(items, allocator, "K")
        self.assertEqual(items[0].metadata["cite"], "K1")
        self.assertEqual(items[1].metadata["cite"], "K2")

    def test_assemble_search_result_passes_dense_degraded(self):
        from unittest.mock import patch

        from docs_core.step09_query.protocols.contracts import RetrievedItem

        from angineer_core.agent_tools import _assemble_search_result

        items = [
            RetrievedItem(
                item_id="a",
                entity_type="content",
                doc_id="d1",
                title="t",
                text="正文",
                score=1.0,
                metadata={"embedding_fallback": True},
            )
        ]
        with patch("angineer_core.retrieval_pipeline.rerank_candidates", return_value=items) as rr:
            _assemble_search_result(
                query="q",
                items=items,
                library_id="default",
                doc_title_map={},
                prefix="K",
                marker_allocator=None,
                rerank=True,
                task_type="content_qa",
                kind="text",
                source="knowledge_search",
                config_name="cfg-y",
                mode="thinking",
            )
        self.assertTrue(rr.call_args.kwargs["dense_degraded"])
        self.assertEqual(rr.call_args.kwargs["config_name"], "cfg-y")
        self.assertEqual(rr.call_args.kwargs["mode"], "thinking")




if __name__ == "__main__":
    unittest.main()
