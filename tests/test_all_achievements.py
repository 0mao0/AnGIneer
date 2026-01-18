
import sys
import os
import json
import unittest
from unittest.mock import MagicMock, patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader
from backend.src.agents import IntentClassifier, Dispatcher
from backend.src.tools import ToolRegistry

# Mock LLM 客户端以防止网络超时和资源消耗
@patch("backend.src.core.llm.llm_client")
class TestPicoAgentAll(unittest.TestCase):
    """
    PicoAgent 综合测试套件。
    涵盖：SOP 加载、路由、调度、混合执行和工具使用。
    """
    
    @classmethod
    def setUpClass(cls):
        print("\n>>> [测试] 正在初始化完整系统测试环境...")
        cls.sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        cls.loader = SopLoader(cls.sop_dir)
        cls.sops = cls.loader.load_all()
        print(f">>> [加载器] 已从索引加载 {len(cls.sops)} 个 SOP。")
        
    def test_01_tool_registration(self, mock_llm):
        """验证所有关键工具是否已注册。"""
        print("\n[测试 01] 正在验证工具注册情况...")
        tools = ToolRegistry.list_tools()
        self.assertIn("table_lookup", tools)
        self.assertIn("knowledge_search", tools)
        self.assertIn("calculator", tools)
        print("  -> 所有核心工具 (TableLookup, KnowledgeSearch, Calculator) 已找到。")
        
    def test_02_intent_classifier(self, mock_llm):
        """测试分类器是否能根据用户查询正确识别 SOP。"""
        print("\n[测试 02] 正在测试意图分类器...")
        
        # 模拟分类器 LLM 响应
        mock_llm.chat.return_value = '{"sop_id": "航道通航底高程", "args": {"DWT": "50000", "ship_type": "oil_tanker"}}'
        
        classifier = IntentClassifier(self.sops)
        query = "计算5万吨级油轮的航道通航底高程"
        sop, args = classifier.route(query)
        
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "航道通航底高程")
        # 参数可能随 LLM 变化，但应包含 '50000' 或类似值
        print(f"  -> 路由至: {sop.id}")
        print(f"  -> 提取的参数: {args}")
        
    def test_03_sop_analysis(self, mock_llm):
        """测试 SOP 的混合分析（将 MD 转换为结构化步骤）。"""
        print("\n[测试 03] 正在测试 SOP 混合分析...")
        
        # 模拟分析响应
        mock_response = """
        ```json
        {
            "steps": [
                {
                    "id": "step1",
                    "name": "确定设计船型尺度",
                    "tool": "table_lookup",
                    "inputs": {"table_name": "油船设计船型尺度", "query_conditions": "DWT=50000"},
                    "notes": "需查询《海港水文规范》附录A"
                },
                {
                    "id": "step2",
                    "name": "计算通航水深",
                    "tool": "calculator",
                    "inputs": {"expression": "T + Z0 + Z1"},
                    "notes": "Z0需根据航速计算"
                }
            ]
        }
        ```
        """
        mock_llm.chat.return_value = mock_response
        
        sop_id = "航道通航底高程"
        analyzed_sop = self.loader.analyze_sop(sop_id)
        
        self.assertGreater(len(analyzed_sop.steps), 0)
        first_step = analyzed_sop.steps[0]
        self.assertIsNotNone(first_step.name)
        # 检查是否提取了 'notes'（混合加载器的功能）
        has_notes = any(step.notes for step in analyzed_sop.steps)
        self.assertTrue(has_notes, "SOP 分析未能提取备注 (Notes)。")
        print(f"  -> 已分析 {len(analyzed_sop.steps)} 个步骤。备注提取状态: {has_notes}")
        
    def test_04_full_execution_flow(self, mock_llm):
        """
        模拟完整执行流程：
        1. 加载 SOP
        2. 提供部分上下文
        3. 调度器运行（通过混合逻辑触发 TableLookup 和 KnowledgeSearch）
        """
        print("\n[测试 04] 正在测试完整执行流程 (混合调度)...")
        
        # 模拟分析响应（同上）
        mock_response = """
        ```json
        {
            "steps": [
                {
                    "id": "step1",
                    "name": "确定设计船型尺度",
                    "tool": "table_lookup",
                    "inputs": {"table_name": "油船设计船型尺度", "query_conditions": "DWT=50000"},
                    "notes": "需查询《海港水文规范》附录A"
                }
            ]
        }
        ```
        """
        # 为后续调用设置一系列返回值
        # 1. 分析 SOP -> 返回上面的 JSON
        # 2. 调度器混合检查 (智能执行) -> 返回 Action JSON
        # 3. TableLookup 工具 -> 返回表格数据 (在工具内部通过 LLM 模拟)
        
        # 需要小心。调度器调用 LLM。TableLookup 调用 LLM。
        # 验证逻辑而不依赖于精确的 LLM 链。
        # 我们可以模拟副作用。
        
        mock_llm.chat.side_effect = [
            mock_response, # 1. 分析 SOP
            '{"action": "table_lookup", "table_name": "油船设计船型尺度", "conditions": "DWT=50000"}', # 2. 调度器决策
            '{"result": {"DWT": 50000, "T": 12.8}}' # 3. TableLookup 工具提取
        ]
        
        sop_id = "航道通航底高程"
        analyzed_sop = self.loader.analyze_sop(sop_id)
        dispatcher = Dispatcher()
        
        initial_context = {
            "user_query": "计算50000吨级油轮的航道通航底高程，设计水深15米",
        }
        
        try:
            final_context = dispatcher.run(analyzed_sop, initial_context)
            print("  -> 执行完成，无错误。")
            print(f"  -> 最终上下文键名: {list(final_context.keys())}")
            
        except Exception as e:
            self.fail(f"调度器执行失败，错误信息: {e}")

    def test_05_table_lookup_tool_direct(self, mock_llm):
        """直接测试 TableLookupTool 以确保其正常工作。"""
        print("\n[测试 05] 正在直接测试 TableLookupTool 调用...")
        
        # 模拟 LLM 提取
        mock_llm.chat.return_value = '{"result": 12.8}'
        
        tool = ToolRegistry.get_tool("table_lookup")
        result = tool.run(table_name="油船设计船型尺度", query_conditions="船舶吨级DWT=50000", target_column="满载吃水T(m)")
        print(f"  -> 查询结果: {result}")
        
        self.assertTrue(isinstance(result, dict))


if __name__ == "__main__":
    unittest.main()
