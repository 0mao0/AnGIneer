
import sys
import os
import unittest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.tools import ToolRegistry

class TestToolRegistration(unittest.TestCase):
    def test_registry_contains_all_tools(self):
        print("\n[测试 01] 工具注册完整性验证")
        print("  -> 步骤 1: 获取工具注册表")
        tools = ToolRegistry.list_tools()
        tool_names = list(tools.keys())
        print(f"     已注册: {', '.join(tool_names)}")

        required_tools = [
            "table_lookup",
            "knowledge_search",
            "calculator",
            "sop_run",
            "web_search",
            "summarizer",
            "code_linter",
            "report_generator",
            "email_sender",
            "file_reader",
            "echo",
            "weather",
            "gis_section_volume_calc"
        ]

        print("  -> 步骤 2: 校验核心工具存在性")
        for name in required_tools:
            with self.subTest(tool=name):
                self.assertIn(name, tools)
                self.assertIsNotNone(ToolRegistry.get_tool(name))

        print("[结果] 工具注册验证通过")

if __name__ == "__main__":
    unittest.main()
