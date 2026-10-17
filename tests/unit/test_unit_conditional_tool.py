"""
单元测试：ConditionalTool table_lookup 分支（B2 修复）。

B2：_execute_table_lookup 从 TableTool import 不存在的 TableTool 类，
触发即 ImportError；修复后不得抛 ImportError。
老 TableLookupTool 删除后分支改走 canonical_table_lookup（无 scope 时返回明确 error dict，
不落默认库、不抛异常）。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from engtools.ConditionalTool import ConditionalTool


class TestConditionalToolTableLookup(unittest.TestCase):
    """B2：table_lookup 分支不得因错误 import 抛 ImportError。"""

    def test_table_lookup_branch_does_not_raise_import_error(self):
        tool = ConditionalTool()
        try:
            result = tool.run(
                condition_var="油船",
                branches=[
                    {
                        "match": "油船",
                        "table_lookup": {
                            "table_name": "表A",
                            "query_conditions": {"船型": "油船"},
                            "file_name": "x",
                            "target_column": "T",
                        },
                    }
                ],
                context={},
            )
        except ImportError as exc:
            self.fail(f"table_lookup 分支不应触发 ImportError（B2）: {exc}")

        self.assertIsInstance(result, dict)


class TestConditionalToolErrorPropagation(unittest.TestCase):
    """分支内嵌子工具的错误必须透传到顶层 error 键（2026-10-17 QA 实踩：
    错误埋在 calculator_result/table_result 里，runner 只认顶层 error，
    导致「分支计算失败但步骤记 success、result=None」假成功，缺参也不进 missing_report）。"""

    def test_calculator_branch_error_propagates_to_top_level(self):
        tool = ConditionalTool()
        result = tool.run(
            condition_var="细沙型",
            branches=[
                {"match": ["细沙型"], "calculator": {"expression": "0.4 * ${有效波高H13} / ${波长L}"}},
            ],
            context={},  # 黑板无参数 → calculator 应报「表达式包含未知量」
        )
        self.assertIsInstance(result, dict)
        self.assertIn("error", result, "calculator 分支失败时顶层必须有 error 键，否则 runner 记假成功")
        self.assertNotIn("result", {k: v for k, v in result.items() if v is not None and k == "result"})

    def test_calculator_branch_success_has_no_error(self):
        tool = ConditionalTool()
        result = tool.run(
            condition_var="细沙型",
            branches=[
                {"match": ["细沙型"], "calculator": {"expression": "0.4 * ${有效波高H13}"}},
            ],
            context={"有效波高H13": 2.0},
        )
        self.assertIsInstance(result, dict)
        self.assertNotIn("error", result)
        self.assertAlmostEqual(result["result"], 0.8, places=6)

    def test_table_lookup_branch_missing_scope_error_at_top_level(self):
        tool = ConditionalTool()
        result = tool.run(
            condition_var="粗沙型",
            branches=[
                {"match": ["粗沙型"], "table_lookup": {
                    "table_name": "图F.0.5", "query_conditions": {}, "file_name": "x", "target_column": "Z"}},
            ],
            context={},  # 无 scope → canonical 路径应报缺 scope
        )
        self.assertIsInstance(result, dict)
        self.assertIn("error", result, "table_lookup 分支缺 scope 时顶层必须有 error 键")


if __name__ == "__main__":
    unittest.main()
