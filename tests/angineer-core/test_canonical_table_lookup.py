"""canonical_table_lookup 单测：fake table_blocks 端口 + 引擎管线行为。

A/B 对齐（与老 TableLookupTool 在真实 SOP 上的结果对比）在接线前另行跑，
此处锁定：scope 透传、端口降级、错误形态、核心取数路径。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core import ports  # noqa: E402
from angineer_core.canonical_table_lookup import canonical_table_lookup  # noqa: E402
from angineer_core.table_query_engine import flatten_header_rows  # noqa: E402


SHIP_TABLE = {
    "doc_id": "doc-hg",
    "header_rows": [["船型", "吨级(t)", "总长L(m)", "型宽B(m)", "型深D(m)", "满载吃水T(m)"]],
    "rows": [
        ["杂货船", "10000", "135", "20.5", "11.0", "8.5"],
        ["杂货船", "40000", "192", "32.2", "17.5", "12.3"],
        ["集装箱船", "40000", "246", "32.2", "19.0", "12.5"],
    ],
    "context": "表A.0.1-1 杂货船设计船型尺度",
    "page_idx": 42,
}
RANGE_TABLE = {
    "doc_id": "doc-hg",
    "header_rows": [["船型", "系数K1"]],
    "rows": [["杂货船", "0.3"]],
    "context": "表A.0.2-2 波浪系数",
    "page_idx": 50,
}


class _TableBlocksPortPatch:
    def __init__(self, blocks):
        self.blocks = blocks
        self.calls = []

    def __enter__(self):
        def fake_provider(library_id="default", doc_ids=None):
            self.calls.append({"library_id": library_id, "doc_ids": doc_ids})
            return self.blocks

        ports.register_agent_search(table_blocks=fake_provider)
        return self

    def __exit__(self, *exc):
        ports.register_agent_search(table_blocks=None)
        return False


class FlattenHeaderRowsTests(unittest.TestCase):
    def test_multi_layer_headers_joined_per_column(self):
        flat = flatten_header_rows([["船舶吨级", "总长", "型宽"], ["DWT(t)", "L(m)", "B(m)"]])
        self.assertEqual(flat, ["船舶吨级 DWT(t)", "总长 L(m)", "型宽 B(m)"])

    def test_single_layer_passthrough(self):
        self.assertEqual(flatten_header_rows([["a", "b"]]), ["a", "b"])


class CanonicalTableLookupTests(unittest.TestCase):
    def test_exact_lookup_with_scope_passthrough(self):
        with _TableBlocksPortPatch([SHIP_TABLE]) as patch:
            result = canonical_table_lookup(
                table_name="表A.0.1-1",
                query_conditions={"船型": "杂货船", "吨级": "40000"},
                target_column="型宽B(m)",
                library_id="lib-x",
                doc_ids=["doc-hg"],
            )
        self.assertEqual(result["result"], 32.2)
        self.assertEqual(result["_source"], "canonical")
        self.assertEqual(result["_doc_id"], "doc-hg")
        self.assertEqual(patch.calls[0]["library_id"], "lib-x")
        self.assertEqual(patch.calls[0]["doc_ids"], ["doc-hg"])

    def test_numeric_condition_picks_best_row(self):
        with _TableBlocksPortPatch([SHIP_TABLE]):
            result = canonical_table_lookup(
                table_name="表A.0.1-1",
                query_conditions={"吨级": "10000"},
                target_column="型宽B(m)",
            )
        self.assertEqual(result["result"], 20.5)

    def test_range_table_name_matches_in_range_candidate(self):
        with _TableBlocksPortPatch([SHIP_TABLE, RANGE_TABLE]):
            result = canonical_table_lookup(
                table_name="表A.0.2-1~表A.0.2-3",
                query_conditions={"船型": "杂货船"},
                target_column="系数K1",
            )
        self.assertEqual(result["result"], 0.3)
        self.assertEqual(result["_table_context"], "表A.0.2-2 波浪系数")

    def test_table_not_found_returns_error(self):
        with _TableBlocksPortPatch([SHIP_TABLE]):
            result = canonical_table_lookup(
                table_name="TableZ-9",
                query_conditions={"船型": "杂货船"},
            )
        self.assertIn("error", result)
        self.assertIn("未找到匹配表格", result["error"])

    def test_empty_conditions_returns_error(self):
        with _TableBlocksPortPatch([SHIP_TABLE]):
            result = canonical_table_lookup(table_name="表A.0.1-1", query_conditions={})
        self.assertIn("error", result)

    def test_no_table_blocks_returns_error(self):
        with _TableBlocksPortPatch([]):
            result = canonical_table_lookup(table_name="表A", query_conditions={"a": "b"})
        self.assertIn("error", result)
        self.assertIn("没有可用的表格块", result["error"])

    def test_missing_port_returns_error(self):
        ports.register_agent_search(table_blocks=None)
        result = canonical_table_lookup(table_name="表A", query_conditions={"a": "b"})
        self.assertIn("error", result)
        self.assertIn("端口未注册", result["error"])

    def test_missing_table_name_returns_error(self):
        result = canonical_table_lookup(table_name="  ", query_conditions={"a": "b"})
        self.assertIn("error", result)

    def test_duplicate_headers_do_not_overwrite_in_row_map(self):
        dup_table = {
            "doc_id": "doc-dup",
            "header_rows": [["组合情况", "上水标准", "上水标准", "受力标准"]],
            "rows": [["基本标准", "设计高水位", "波浪值", "50年"]],
            "context": "表5.4.8 组合标准",
            "page_idx": 0,
        }
        with _TableBlocksPortPatch([dup_table]):
            result = canonical_table_lookup(table_name="表5.4.8", query_conditions={"水位": "设计高水位"})
        row = result["result"]
        self.assertEqual(row["上水标准"], "设计高水位")
        self.assertEqual(row["上水标准#2"], "波浪值")


if __name__ == "__main__":
    unittest.main()
