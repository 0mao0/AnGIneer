
import sys
import os
import unittest
from unittest.mock import patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader
from backend.src.agents import Dispatcher

@patch("backend.src.core.llm.llm_client")
class TestFullExecutionFlow(unittest.TestCase):
    """模拟完整执行流程 (混合调度)。"""
    
    def test_run(self, mock_llm):
        print("\n[测试 04] 正在启动完整执行流程测试 (混合调度)...")
        
        sop_id = "航道通航底高程"
        print(f"  -> 步骤 1: 准备测试数据，SOP ID: {sop_id}")
        
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
        mock_llm.chat.side_effect = [
            mock_response, # 1. 分析 SOP
            '{"action": "table_lookup", "table_name": "油船设计船型尺度", "conditions": "DWT=50000"}', # 2. 调度器决策
            '{"result": {"DWT": 50000, "T": 12.8}}' # 3. TableLookup 工具提取
        ]
        print("  -> 步骤 2: 已配置 Mock LLM 响应流 (分析 -> 决策 -> 提取)")
        
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)
        
        print(f"  -> 步骤 1: 正在初始化测试...")
        print(f"     [CALL] src/core/sop_loader.py -> SopLoader.analyze_sop()")
        analyzed_sop = loader.analyze_sop(sop_id)
        print(f"     [OK] 已加载并分析 SOP: {sop_id}")
        
        print(f"  -> 步骤 2: 正在启动 Dispatcher...")
        
        dispatcher = Dispatcher()
        initial_context = {
            "user_query": "计算50000吨级油轮的航道通航底高程，设计水深15米",
        }
        
        try:
            print(f"     [CALL] src/core/dispatcher.py -> Dispatcher.run()")
            final_context = dispatcher.run(analyzed_sop, initial_context)
            print("  -> 步骤 5: 验证执行结果...")
            print(f"     [OK] 执行完成，无错误。")
            print(f"     [OK] 最终上下文键名: {list(final_context.keys())}")
            self.assertIn("DWT", final_context)
            self.assertIn("T", final_context)
        except Exception as e:
            print(f"     [FAILED] 调度器执行失败: {e}")
            self.fail(f"调度器执行失败，错误信息: {e}")
        
        print("\n[结果] 完整执行流程验证通过。")

if __name__ == "__main__":
    unittest.main()
