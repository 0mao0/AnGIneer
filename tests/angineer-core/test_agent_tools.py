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




class RetrievalStageOpsTests(unittest.TestCase):
    """方案 E（req-table-retrieval-latency §10）：stage_times 上浮 → kind=retrieval 落盘。"""

    def setUp(self):
        import tempfile

        self._tmp = tempfile.TemporaryDirectory()
        self._old = {k: os.environ.get(k) for k in ("ANGINEER_OPS_DIR", "ANGINEER_OPS_DISABLE")}
        os.environ["ANGINEER_OPS_DIR"] = self._tmp.name
        os.environ.pop("ANGINEER_OPS_DISABLE", None)  # conftest 全局停用，本类显式启用
        from angineer_core import ops_metrics

        self.ops = ops_metrics
        self.ops.set_run_id("run-e2e")

    def tearDown(self):
        self.ops.set_run_id(None)
        for k, v in self._old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        self._tmp.cleanup()

    def _rows(self, kind: str):
        import json as _json

        files = [f for f in os.listdir(self._tmp.name) if f.startswith(f"{kind}-")]
        out = []
        for name in files:
            with open(os.path.join(self._tmp.name, name), encoding="utf-8") as f:
                out.extend(_json.loads(l) for l in f if l.strip())
        return out

    def test_records_stages_with_context_run_id(self):
        from angineer_core.agent_tools import _record_retrieval_stages

        _record_retrieval_stages(
            "table_search",
            {"items": [], "stage_times": {"table": 2.61, "formula": 1.13, "fuse": 0.0}},
            query="码头前沿水深富裕高度 散货船 5万吨级 规范",
            task_type="table_qa",
            top_k=20,
            library_id="default",
        )
        rows = self._rows("retrieval")
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["path"], "table_search")
        self.assertEqual(row["run_id"], "run-e2e")
        self.assertEqual(row["task_type"], "table_qa")
        self.assertEqual(row["dur_ms"], 3740)
        self.assertEqual(row["stages"]["table"], 2.61)

    def test_skips_silently_without_stage_times(self):
        from angineer_core.agent_tools import _record_retrieval_stages

        _record_retrieval_stages("knowledge_search", {"items": []}, query="q", task_type="content_qa", top_k=20, library_id="default")
        _record_retrieval_stages("knowledge_search", "not-a-dict", query="q", task_type="content_qa", top_k=20, library_id="default")
        self.assertEqual(self._rows("retrieval"), [])


if __name__ == "__main__":
    unittest.main()
