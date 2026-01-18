
import sys
import os
import unittest
from unittest.mock import patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.tools import ToolRegistry

class TestToolRegistration(unittest.TestCase):
    """验证所有关键工具是否已注册。"""
    
    def test_run(self):
        print("\n[测试 01] 正在启动工具注册验证流程...")
        print(f"  -> 步骤 1: 检查工具源码目录")
        print(f"     目录: {os.path.abspath(os.path.join(os.path.dirname(__file__), '../backend/src/tools'))}")
        
        print(f"  -> 步骤 2: 获取注册表工具列表")
        print(f"     [CALL] src/tools/__init__.py -> ToolRegistry.list_tools()")
        tools = ToolRegistry.list_tools()
        print(f"     已注册: {', '.join(tools)}")
        
        required_tools = ["table_lookup", "knowledge_search", "calculator", "sop_run"]
        print(f"  -> 步骤 3: 验证核心工具存在性")
        for tool in required_tools:
            with self.subTest(tool=tool):
                print(f"     正在验证: {tool}")
                self.assertIn(tool, tools)
                print(f"     [OK] 工具 '{tool}' 已注册。")
        
        print("\n[结果] 所有核心工具验证通过。")

if __name__ == "__main__":
    unittest.main()
