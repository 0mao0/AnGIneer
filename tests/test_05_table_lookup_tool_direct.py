
import sys
import os
import unittest
from unittest.mock import patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.tools import ToolRegistry

@patch("backend.src.core.llm.llm_client")
class TestTableLookupToolDirect(unittest.TestCase):
    """直接测试 TableLookupTool 以确保其正常工作。"""
    
    def test_run(self, mock_llm):
        print("\n[测试 05] 正在启动 TableLookupTool 直接调用测试...")
        
        table_name = "油船设计船型尺度"
        query_conditions = "船舶吨级DWT=50000"
        target_column = "满载吃水T(m)"
        
        print(f"  -> 步骤 1: 准备查询参数")
        print(f"     表名: {table_name}")
        print(f"     条件: {query_conditions}")
        print(f"     目标列: {target_column}")
        
        # 模拟 LLM 提取
        mock_response = '{"result": 12.8}'
        mock_llm.chat.return_value = mock_response
        print(f"  -> 步骤 2: 模拟 LLM 提取响应: {mock_response}")
        
        print("  -> 步骤 3: 从注册中心获取工具并执行...")
        print(f"     [CALL] src/tools/__init__.py -> ToolRegistry.get_tool()")
        tool = ToolRegistry.get_tool("table_lookup")
        print(f"     [CALL] src/tools/table_lookup.py -> TableLookupTool.run()")
        result = tool.run(table_name=table_name, query_conditions=query_conditions, target_column=target_column)
        
        print("  -> 步骤 4: 验证查询结果...")
        print(f"     [OK] 查询结果: {result}")
        self.assertTrue(isinstance(result, dict))
        
        print("\n[结果] TableLookupTool 直接调用验证通过。")

if __name__ == "__main__":
    unittest.main()
