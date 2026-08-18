"""P2 工具契约与适配器单测。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))

from engtools.BaseTool import BaseTool, ToolRegistry  # noqa: E402
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

    def test_assign_cites_and_citations_marker_consistent(self):
        from angineer_core.agent_tools import MarkerAllocator, _assign_cites, _build_relevant_citations
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
        citations = _build_relevant_citations("船闸规范", items)
        self.assertEqual(items[0].metadata["cite"], "K1")
        self.assertEqual(citations[0]["marker"], "K1")
        self.assertEqual(citations[0]["target_id"], "a")

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


class KnowledgeSearchFormulaTests(unittest.TestCase):
    def test_formula_query_includes_formula_context(self):
        from unittest.mock import patch

        from docs_core.step09_query.protocols.contracts import RetrievedItem

        from angineer_core.agent_tools import _run_knowledge_search

        fake_item = RetrievedItem(
            item_id="ctx-1",
            entity_type="formula_context",
            doc_id="d1",
            title="6.2 航道建设规模及航行标准",
            text="式中 t_{1} ——每潮次船舶通过航道的持续时间(h)",
            score=10.0,
            retrieval_policy="formula_context",
            metadata={"source_kind": "formula_context", "chunk_type": "formula_context"},
        )
        with patch("docs_core.step09_query.retrieval.formula_retriever.FormulaRetriever") as cls:
            cls.return_value.retrieve.return_value = [fake_item]
            result = _run_knowledge_search(
                query="乘潮进港时间怎么算",
                library_id="default",
                doc_ids=[],
                doc_nodes=[],
                top_k=20,
                task_type="content_qa",
            )
        items = result.get("items") or []
        self.assertTrue(any(item.get("item_id") == "ctx-1" for item in items))

    def test_non_formula_query_skips_formula_retriever(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _run_knowledge_search

        with patch("docs_core.step09_query.retrieval.formula_retriever.FormulaRetriever") as cls:
            _run_knowledge_search(
                query="上航数联是什么",
                library_id="default",
                doc_ids=[],
                doc_nodes=[],
                top_k=20,
                task_type="content_qa",
            )
        cls.assert_not_called()


if __name__ == "__main__":
    unittest.main()
