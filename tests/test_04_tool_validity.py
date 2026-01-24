
import sys
import os
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.tools import ToolRegistry

"""
工具能力覆盖测试脚本 (Test 04)
对系统内置的所有工具（表格查询、知识检索、计算器、GIS 计算等）进行功能验证。
"""

@patch("src.core.llm.llm_client")
class TestToolBehaviorSuite(unittest.TestCase):
    def test_tool_behaviors(self, mock_llm):
        print("\n[测试 04] 工具有效性测试")
        mock_llm.chat.side_effect = [
            '{"result": {"DWT": 50000, "T": 12.8}}',
            "相关条文片段"
        ]

        print("  -> 步骤 1: 表格查询工具")
        table_tool = ToolRegistry.get_tool("table_lookup")
        table_result = table_tool.run(
            table_name="油船设计船型尺度",
            query_conditions="DWT=50000",
            target_column="满载吃水T(m)"
        )
        self.assertTrue(isinstance(table_result, dict))
        self.assertIn("result", table_result)

        print("  -> 步骤 2: 知识检索工具")
        knowledge_tool = ToolRegistry.get_tool("knowledge_search")
        knowledge_result = knowledge_tool.run(query="航道通航底高程")
        self.assertTrue(isinstance(knowledge_result, dict))
        self.assertIn("result", knowledge_result)

        print("  -> 步骤 3: 计算器")
        calculator = ToolRegistry.get_tool("calculator")
        calc_result = calculator.run(expression="12 + 30")
        self.assertEqual(calc_result, 42)

        print("  -> 步骤 4: GIS 计算")
        gis_tool = ToolRegistry.get_tool("gis_section_volume_calc")
        gis_result = gis_tool.run(design_depth=12.5, design_width=150, length=1000)
        self.assertTrue(isinstance(gis_result, dict))
        self.assertIn("total_volume_m3", gis_result)

        print("  -> 步骤 5: 代码检查与文件读取")
        file_reader = ToolRegistry.get_tool("file_reader")
        code_text = file_reader.run(file_path="demo/code.py")
        linter = ToolRegistry.get_tool("code_linter")
        lint_result = linter.run(code=code_text)
        self.assertTrue(isinstance(lint_result, str))
        self.assertIn("除以零", lint_result)

        print("  -> 步骤 6: 报告与摘要")
        report_tool = ToolRegistry.get_tool("report_generator")
        report = report_tool.run(title="测试报告", data={"ok": True})
        self.assertTrue(report.startswith("# 测试报告"))
        summarizer = ToolRegistry.get_tool("summarizer")
        summary = summarizer.run(text=report, max_words=20)
        self.assertTrue(isinstance(summary, str))

        print("  -> 步骤 7: 其他工具")
        email_sender = ToolRegistry.get_tool("email_sender")
        email_result = email_sender.run(recipient="test@example.com", subject="Hi", body="Body")
        self.assertIn("邮件已发送", email_result)
        web_search = ToolRegistry.get_tool("web_search")
        search_result = web_search.run(query="market trend")
        self.assertTrue(isinstance(search_result, dict))
        echo = ToolRegistry.get_tool("echo")
        self.assertEqual(echo.run(message="ping"), "ping")
        weather = ToolRegistry.get_tool("weather")
        self.assertIn("天气", weather.run(city="深圳"))
        sop_run = ToolRegistry.get_tool("sop_run")
        sop_result = sop_run.run(filename="demo.md", question="如何处理")
        self.assertIn("已启动子流程", sop_result)

if __name__ == "__main__":
    unittest.main()
