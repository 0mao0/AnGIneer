"""
单元测试：ConditionalTool table_lookup 分支（B2 修复）。

B2：_execute_table_lookup 从 TableTool import 不存在的 TableTool 类，
触发即 ImportError；修复后不得抛 ImportError。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))

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


if __name__ == "__main__":
    unittest.main()
