"""SOP table_lookup 接线 canonical 的单测：scope 透传、file_name 转译、错误形态。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core import ports  # noqa: E402
from angineer_core.base_contracts import SOP, Step  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402


LOOKUP_TABLE = {
    "doc_id": "doc-hg",
    "header_rows": [["船型", "吨级(t)", "满载吃水T(m)"]],
    "rows": [["杂货船", "40000", "12.3"]],
    "context": "表A.0.2-3 设计船型尺度",
    "page_idx": 133,
}

# 真实 canonical 表的形态：父表头「船舶主要尺度(m)」重复 4 次，
# 子表头（总长L/型宽B/型深H/满载吃水T）落进 body 首行。
DUP_TABLE = {
    "doc_id": "doc-hg-dup",
    "header_rows": [[
        "序号", "船名", "载重吨DWT(t)",
        "船舶主要尺度(m)", "船舶主要尺度(m)", "船舶主要尺度(m)", "船舶主要尺度(m)",
    ]],
    "rows": [
        ["序号", "船名", "载重吨DWT(t)", "总长L", "型宽B", "型深H", "满载吃水T"],
        ["1", "矿石船", "100000", "254", "43", "22", "14.5"],
        ["2", "矿石船", "50000", "200", "32", "18", "11.2"],
    ],
    "context": "表A.0.2-1 散货船船舶主要尺度",
    "page_idx": 131,
}


def make_lookup_sop(inputs):
    return SOP(
        id="sop-tl",
        name_zh="查表SOP",
        steps=[
            Step(
                id="s1",
                name_zh="查表",
                tool="table_lookup",
                inputs=inputs,
                outputs={"T": "result"},
            )
        ],
    )


class _PortsPatch:
    """注册 table_blocks + local_nodes_loader 两个 fake 端口，finally 清除。"""

    def __init__(self, blocks=None, nodes=None):
        self.blocks = blocks if blocks is not None else [LOOKUP_TABLE]
        self.nodes = nodes or []
        self.provider_calls = []

    def __enter__(self):
        def provider(library_id="default", doc_ids=None):
            self.provider_calls.append({"library_id": library_id, "doc_ids": doc_ids})
            return self.blocks

        ports.register_agent_search(table_blocks=provider)
        ports.register_local_nodes_loader(lambda library_id, doc_ids=None: self.nodes)
        return self

    def __exit__(self, *exc):
        ports.register_agent_search(table_blocks=None)
        ports.register_local_nodes_loader(None)
        return False


class SopTableLookupCanonicalTests(unittest.TestCase):
    def test_lookup_uses_runner_scope(self):
        runner = SopRunner(llm_client=Mock(), library_id="lib-x", doc_ids=["doc-hg"])
        with _PortsPatch() as patch:
            blackboard = runner.run_sop(
                make_lookup_sop({"table_name": "表A.0.2-3", "query_conditions": {"船型": "杂货船", "吨级": "40000"}, "target_column": "满载吃水T(m)"}),
                {"user_query": "查 T"},
            )
        self.assertEqual(blackboard["T"], 12.3)
        self.assertEqual(patch.provider_calls[0]["library_id"], "lib-x")
        self.assertEqual(patch.provider_calls[0]["doc_ids"], ["doc-hg"])
        self.assertEqual(runner.memory.history[0].status, "success")

    def test_tonnage_alias_and_subheader_resolve_T(self):
        """吨级→载重吨DWT(t) 别名 + 子表头展开：不传 target_column 也能取到 T。"""
        runner = SopRunner(llm_client=Mock())
        with patch.dict(os.environ, {"ANGINEER_SOP_DOMAIN_PACK": "harbor"}):
            from angineer_core import sop_domain

            sop_domain._cache.pop("harbor", None)
            with _PortsPatch(blocks=[DUP_TABLE]):
                blackboard = runner.run_sop(
                    make_lookup_sop({
                        "table_name": "表A.0.2-1",
                        "query_conditions": {"船型": "矿石船", "吨级": "100000"},
                    }),
                    {},
                )
        self.assertEqual(blackboard["T"], 14.5)
        self.assertEqual(runner.memory.history[0].status, "success")

    def test_file_name_translated_to_doc_scope(self):
        nodes = [SimpleNamespace(id="doc-hg", title="JTS 165-2013 海港总体设计规范.pdf", type="document")]
        runner = SopRunner(llm_client=Mock())
        with _PortsPatch(nodes=nodes) as patch:
            blackboard = runner.run_sop(
                make_lookup_sop({
                    "table_name": "表A.0.2-3",
                    "query_conditions": {"船型": "杂货船", "吨级": "40000"},
                    "target_column": "满载吃水T(m)",
                    "file_name": "海港总体设计规范_JTS_165-2025",
                }),
                {},
            )
        self.assertEqual(blackboard["T"], 12.3)
        self.assertEqual(patch.provider_calls[0]["doc_ids"], ["doc-hg"])

    def test_unresolvable_file_name_errors_without_full_scan(self):
        runner = SopRunner(llm_client=Mock())
        with _PortsPatch(nodes=[]) as patch:
            runner.run_sop(
                make_lookup_sop({
                    "table_name": "表A.0.2-3",
                    "query_conditions": {"船型": "杂货船"},
                    "file_name": "不存在的规范_XX_0000",
                }),
                {},
            )
        self.assertEqual(runner.memory.history[0].status, "failed")
        self.assertIn("未找到知识库文件", runner.memory.history[0].error)
        self.assertEqual(patch.provider_calls, [])  # 未解析时不许落到 provider 全库扫

    def test_canonical_error_passes_through(self):
        runner = SopRunner(llm_client=Mock())
        with _PortsPatch(blocks=[]):
            runner.run_sop(
                make_lookup_sop({"table_name": "表A.0.2-3", "query_conditions": {"船型": "杂货船"}}),
                {},
            )
        self.assertEqual(runner.memory.history[0].status, "failed")
        self.assertIn("没有可用的表格块", runner.memory.history[0].error)


if __name__ == "__main__":
    unittest.main()
