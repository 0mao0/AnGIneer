"""P2 工具契约与适配器单测。"""
import os
import sys
import unittest
from unittest import mock

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


def _cap_item(item_id: str, text: str):
    """可被 _serialize_model 处理的假检索条目（dataclass 走字段展开分支）。"""
    from dataclasses import dataclass, field as dc_field

    @dataclass
    class _FakeItem:
        item_id: str
        text: str
        doc_id: str = "d1"
        title: str = "t"
        score: float = 1.0
        rerank_score: float = None
        metadata: dict = dc_field(default_factory=dict)
        citation_target_id: str = None

    return _FakeItem(item_id=item_id, text=text)


class EvidenceCapTests(unittest.TestCase):
    """软帽 _apply_evidence_cap（变更 B）：按 rank 装填、剩余 <200 字符整条丢、0=关帽。"""

    def _item(self, item_id, n):
        from types import SimpleNamespace

        return SimpleNamespace(item_id=item_id, text="x" * n)

    # 说明：_apply_evidence_cap 只读写 .text，SimpleNamespace 足够；
    # 进 _serialize_model 的用例（AdmissionWiringTests）必须用 _cap_item（dataclass）。

    def test_cap_drops_items_over_budget(self):
        from angineer_core.agent_tools import _apply_evidence_cap

        items = [self._item("a", 80), self._item("b", 80), self._item("c", 80)]
        with mock.patch.dict(os.environ, {"ANGINEER_EVIDENCE_CAP_EST": "100"}):  # budget=200 字符
            kept, dropped = _apply_evidence_cap(items)
        self.assertEqual([i.item_id for i in kept], ["a", "b"])
        self.assertEqual(dropped, 1)

    def test_cap_truncates_partial_item(self):
        from angineer_core.agent_tools import _apply_evidence_cap

        items = [self._item("a", 100), self._item("b", 500)]
        with mock.patch.dict(os.environ, {"ANGINEER_EVIDENCE_CAP_EST": "150"}):  # budget=300
            kept, dropped = _apply_evidence_cap(items)
        self.assertEqual([i.item_id for i in kept], ["a", "b"])
        self.assertEqual(len(kept[1].text), 200)  # 剩余预算 200 ≥200 → 截尾保留
        self.assertEqual(dropped, 0)

    def test_cap_zero_disabled(self):
        from angineer_core.agent_tools import _apply_evidence_cap

        items = [self._item("a", 5000)]
        with mock.patch.dict(os.environ, {"ANGINEER_EVIDENCE_CAP_EST": "0"}):
            kept, dropped = _apply_evidence_cap(items)
        self.assertIs(kept, items)
        self.assertEqual(dropped, 0)

    def test_entity_cap_drops_over_budget(self):
        """entity_search 纯实体不经 _assemble_search_result，软帽就地补装（超帽整条丢）。"""
        from dataclasses import dataclass

        from angineer_core.agent_tools import _cap_entity_objects

        @dataclass
        class _FakeEntity:
            entity_id: str
            name: str
            description: str

        entities = [_FakeEntity("e1", "混凝土", "标号 C30"), _FakeEntity("e2", "钢筋", "HRB400")]
        with mock.patch.dict(os.environ, {"ANGINEER_EVIDENCE_CAP_EST": "1"}):  # budget=2 字符
            kept, dropped = _cap_entity_objects(entities)
        self.assertEqual(kept, [])
        self.assertEqual(dropped, 2)


class AdmissionWiringTests(unittest.TestCase):
    """_maybe_admit_evidence 触发门与 _assemble_search_result 留痕（变更 A/B 接线）。"""

    def _items(self, n=3, size=50):
        return [_cap_item(str(i), "x" * size) for i in range(n)]

    def test_oversize_mode_skips_normal_packet(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _maybe_admit_evidence

        items = self._items()
        with mock.patch.dict(os.environ, {"ANGINEER_ADMISSION_MODE": "oversize"}):
            with patch("angineer_core.retrieval_pipeline.admit_evidence") as admit:
                out, block = _maybe_admit_evidence("q", items)
        admit.assert_not_called()
        self.assertIs(out, items)
        self.assertIsNone(block)

    def test_off_mode_skips_even_pathological(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _maybe_admit_evidence

        items = self._items(n=15, size=20000)
        env = {"ANGINEER_ADMISSION_MODE": "off", "ANGINEER_ADMISSION_TRIGGER_EST": "1"}
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.admit_evidence") as admit:
                out, block = _maybe_admit_evidence("q", items)
        admit.assert_not_called()
        self.assertIsNone(block)

    def test_oversize_triggers_on_precap_est(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _maybe_admit_evidence

        items = self._items(n=3, size=100)  # est=150 > 触发阈值 10
        block = {"kept": 2, "dropped": 1, "quarreled": 0, "exempted": 0,
                 "fallback": False, "judge_config": "cfg", "judge_ms": 5}
        env = {"ANGINEER_ADMISSION_MODE": "oversize", "ANGINEER_ADMISSION_TRIGGER_EST": "10"}
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.admit_evidence", return_value=(items[:2], block)) as admit:
                out, got = _maybe_admit_evidence("q", items)
        admit.assert_called_once()
        self.assertEqual(len(admit.call_args.args[1]), 3)  # 判官看到的是全部原始条目
        self.assertEqual(len(out), 2)
        self.assertIs(got, block)

    def test_assemble_cap_dropped_lands_in_admission_block(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _assemble_search_result

        items = self._items(n=3, size=400)
        env = {"ANGINEER_EVIDENCE_CAP_EST": "1", "ANGINEER_EVIDENCE_GRADE": "0", "ANGINEER_ADMISSION_MODE": "off"}
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.rerank_candidates", return_value=items):
                result = _assemble_search_result(
                    query="q", items=items, library_id="default", doc_title_map={}, prefix="K",
                    marker_allocator=None, rerank=True, task_type="content_qa",
                    kind="text", source="knowledge_search",
                )
        block = result["_admission"]
        self.assertEqual(block["cap_dropped"], 3)  # budget=2 字符 → 全部整条丢
        self.assertEqual(result["total"], 0)
        for key in ("kept", "dropped", "quarreled", "exempted", "fallback", "judge_config", "judge_ms"):
            self.assertIn(key, block)  # 判官没跑也发全字段（None），nightly 归因判据统一
        self.assertIsNone(block["kept"])

    def test_assemble_admission_before_cap(self):
        """顺序钉死：上桌（判官读帽前全量）→ 软帽。帽极小也不影响判官输入条数。"""
        from unittest.mock import patch

        from angineer_core.agent_tools import _assemble_search_result

        items = self._items(n=3, size=400)
        block = {"kept": 2, "dropped": 1, "quarreled": 0, "exempted": 0,
                 "fallback": False, "judge_config": "cfg", "judge_ms": 7}
        env = {
            "ANGINEER_ADMISSION_MODE": "oversize", "ANGINEER_ADMISSION_TRIGGER_EST": "10",
            "ANGINEER_EVIDENCE_CAP_EST": "1", "ANGINEER_EVIDENCE_GRADE": "0",
        }
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.rerank_candidates", return_value=items), \
                 patch("angineer_core.retrieval_pipeline.admit_evidence", return_value=(list(items), block)) as admit:
                result = _assemble_search_result(
                    query="q", items=items, library_id="default", doc_title_map={}, prefix="K",
                    marker_allocator=None, rerank=True, task_type="content_qa",
                    kind="text", source="knowledge_search",
                )
        self.assertEqual(len(admit.call_args.args[1]), 3)  # 帽前口径：判官见原始 3 条
        merged = result["_admission"]
        self.assertEqual(merged["kept"], 2)  # 上桌计数保留
        self.assertEqual(merged["cap_dropped"], 3)  # 帽子另计（上桌丢与帽子丢分开）

    def test_assemble_empty_table_no_fallback(self):
        from unittest.mock import patch

        from angineer_core.agent_tools import _assemble_search_result

        items = self._items(n=3, size=400)
        block = {"kept": 0, "dropped": 3, "quarreled": 0, "exempted": 0,
                 "fallback": False, "judge_config": "cfg", "judge_ms": 9}
        env = {
            "ANGINEER_ADMISSION_MODE": "oversize", "ANGINEER_ADMISSION_TRIGGER_EST": "10",
            "ANGINEER_EVIDENCE_CAP_EST": "80000", "ANGINEER_EVIDENCE_GRADE": "0",
        }
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.rerank_candidates", return_value=items), \
                 patch("angineer_core.retrieval_pipeline.admit_evidence", return_value=([], block)):
                result = _assemble_search_result(
                    query="q", items=items, library_id="default", doc_title_map={}, prefix="K",
                    marker_allocator=None, rerank=True, task_type="content_qa",
                    kind="text", source="knowledge_search",
                )
        self.assertEqual(result["total"], 0)  # 空桌不回退：items 空→下游无证据守卫出标准拒答
        self.assertEqual(result["_admission"]["dropped"], 3)

    def test_table_kind_never_goes_to_admission(self):
        """上桌只管 knowledge_search 文本条目；table_search 只走硬帽。"""
        from unittest.mock import patch

        from angineer_core.agent_tools import _assemble_search_result

        items = self._items(n=3, size=400)
        env = {"ANGINEER_ADMISSION_MODE": "all", "ANGINEER_EVIDENCE_CAP_EST": "80000", "ANGINEER_EVIDENCE_GRADE": "0"}
        with mock.patch.dict(os.environ, env):
            with patch("angineer_core.retrieval_pipeline.rerank_candidates", return_value=items), \
                 patch("angineer_core.retrieval_pipeline.admit_evidence") as admit:
                result = _assemble_search_result(
                    query="q", items=items, library_id="default", doc_title_map={}, prefix="T",
                    marker_allocator=None, rerank=True, task_type="table_qa",
                    kind="table", source="table_search",
                )
        admit.assert_not_called()
        self.assertEqual(result["total"], 3)
        self.assertNotIn("_admission", result)  # 无上桌、帽未丢 → 不发块


if __name__ == "__main__":
    unittest.main()
