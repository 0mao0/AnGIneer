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

    def test_range_name_skips_table_whose_rows_miss_conditions(self):
        """范围表名并列评分时按「能否真正匹配到行」选表（2026-10-14 实踩复现：
        表A.0.2-1~14 并列 280 分、旧逻辑取分最高一张=渡船表 → 文本条件全灭 →
        「未找到符合文本条件的行」→ SOP 整链缺参拒答）。"""
        decoy = {
            "doc_id": "doc-hg",
            "header_rows": [["船型", "吨级(t)", "总长L(m)"]],
            "rows": [["渡船", "100000", "30.0"]],
            # 与现场一致：错表的 context 里也提了「散货」（评分反超真表）
            "context": "表A.0.2-1 渡船设计船型尺度表 A.0.2 散货/集装船分册索引",
            "page_idx": 60,
        }
        real = {
            "doc_id": "doc-hg",
            "header_rows": [["船型", "吨级(t)", "型宽B(m)", "满载吃水T(m)"]],
            "rows": [["散货船", "100000", "32.0", "14.5"]],
            "context": "表A.0.2-2 设计船型尺度（第二分册）",
            "page_idx": 61,
        }
        with _TableBlocksPortPatch([decoy, real]):
            result = canonical_table_lookup(
                table_name="表A.0.2-1~表A.0.2-14",
                query_conditions={"船型": "散货船", "吨级": "100000"},
            )
        # 断言本修复的契约：选中能匹配到行的真表（而非评分更高但行全灭的错表），并留痕。
        # （取值形态由后续 target-col 启发式决定，不在本测试范围。）
        self.assertEqual(result["_table_context"], "表A.0.2-2 设计船型尺度（第二分册）")
        self.assertNotIn("error", result)
        self.assertIn("表格选择策略: 范围表名按行匹配可行性重选", result["_trace"])

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


class TitleMatchesTests(unittest.TestCase):
    """file_name → 文档标题匹配（2026-10-12 收紧：分册号参与比较 + 主名重叠闸）。"""

    def test_cross_volume_code_not_matched(self):
        # 实踩锚：海港总体设计规范_JTS_165-2025 曾错配到 JTS 165-5-2016 液化天然气码头设计规范
        from angineer_core.canonical_table_lookup import _title_matches
        self.assertFalse(_title_matches(
            "海港总体设计规范 jts 165-2025",
            "jts 165-5-2016 液化天然气码头设计规范(附条文说明)",
        ))

    def test_same_spec_year_variant_matched(self):
        from angineer_core.canonical_table_lookup import _title_matches
        self.assertTrue(_title_matches(
            "海港总体设计规范 jts 165-2025",
            "海港总体设计规范 jts 165-2013",
        ))

    def test_code_match_requires_name_overlap(self):
        # 编号（含分册/年份）一致但主名不同 → 不匹配
        from angineer_core.canonical_table_lookup import _title_matches
        self.assertFalse(_title_matches(
            "液化天然气码头设计规范 jts 165-5",
            "海港总体设计规范 jts 165-5",
        ))

    def test_suffix_variants_matched(self):
        from angineer_core.canonical_table_lookup import _title_matches
        self.assertTrue(_title_matches(
            "海港总体设计规范",
            "海港总体设计规范(附条文说明)",
        ))

    def test_spec_code_extraction(self):
        from angineer_core.canonical_table_lookup import _extract_spec_code
        self.assertEqual(_extract_spec_code("jts 165-2013"), ("jts", "165", None))
        self.assertEqual(_extract_spec_code("jts 165-5-2016"), ("jts", "165", "5"))
        self.assertIsNone(_extract_spec_code("没有编号的文档"))


class NumberRefSelectionTests(unittest.TestCase):
    """表号形态（表5.4.8）：编号对不上时必须显式报错，禁止拆词兜底抓错表（修复 A）。"""

    LNG_BLOCKS = [
        {"doc_id": "doc-x", "header_rows": [["类别", "大型", "中型"]],
         "rows": [["A", "1", "2"]], "context": "表 1.0.3 液化天然气码头分类表"},
        {"doc_id": "doc-x", "header_rows": [["条件", "值"]],
         "rows": [["x", "1"]], "context": "表 4.0.2 液化天然气船舶作业条件标准"},
    ]

    def test_number_ref_miss_returns_explicit_error(self):
        with _TableBlocksPortPatch(list(self.LNG_BLOCKS)):
            result = canonical_table_lookup(
                table_name="表5.4.8", query_conditions={"掩护情况": "部分掩护"},
                library_id="default", doc_ids=["doc-x"],
            )
        self.assertIn("均无编号", result["error"])
        self.assertNotIn("result", result)

    def test_number_ref_hit_still_selects(self):
        blocks = list(self.LNG_BLOCKS) + [
            {"doc_id": "doc-x", "header_rows": [["掩护情况", "Δw1"]],
             "rows": [["部分掩护", "0.5"]], "context": "表 5.4.8 码头前沿顶高程"},
        ]
        with _TableBlocksPortPatch(blocks):
            result = canonical_table_lookup(
                table_name="表5.4.8", query_conditions={},
                library_id="default", doc_ids=["doc-x"],
            )
        # 选中走空条件分支（错误信息里带回所选表的 context 可佐证选表正确）
        self.assertIn("表 5.4.8", str(result.get("_table_context") or ""))

    def test_normal_table_name_unaffected(self):
        with _TableBlocksPortPatch(list(self.LNG_BLOCKS)):
            result = canonical_table_lookup(
                table_name="液化天然气码头分类表", query_conditions={},
                library_id="default", doc_ids=["doc-x"],
            )
        self.assertEqual(result.get("_table_context"), "表 1.0.3 液化天然气码头分类表")

    def test_is_table_number_ref_predicate(self):
        from angineer_core.table_query_engine import _is_table_number_ref
        for name in ("表5.4.8", "表 5.4.8", "表A.0.1", "表5.4.8-1"):
            self.assertTrue(_is_table_number_ref(name), name)
        for name in ("液化天然气码头分类表", "杂货船设计船型尺度", "表A"):
            self.assertFalse(_is_table_number_ref(name), name)

if __name__ == "__main__":
    unittest.main()
