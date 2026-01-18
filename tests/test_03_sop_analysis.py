
import sys
import os
import unittest
from unittest.mock import patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader

@patch("backend.src.core.llm.llm_client")
class TestSopAnalysis(unittest.TestCase):
    """测试 SOP 的混合分析（将 MD 转换为结构化步骤）。"""
    
    def test_run(self, mock_llm):
        print("\n[测试 03] 正在启动 SOP 混合分析测试...")
        
        sop_id = "航道通航底高程"
        print(f"  -> 步骤 1: 模拟分析 SOP 模板: {sop_id}")
        
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
        print(f"  -> 步骤 2: 模拟 LLM 解析 MD 为结构化 JSON...")
        
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)
        
        print(f"     [CALL] src/core/sop_loader.py -> SopLoader.analyze_sop()")
        analyzed_sop = loader.analyze_sop(sop_id)
        
        print("  -> 步骤 3: 验证解析后的 SOP 对象...")
        self.assertGreater(len(analyzed_sop.steps), 0)
        print(f"     [OK] 成功解析出 {len(analyzed_sop.steps)} 个步骤。")
        
        for i, step in enumerate(analyzed_sop.steps):
            print(f"     - 步骤 {i+1}: {step.name} (工具: {step.tool})")
            if step.notes:
                print(f"       备注: {step.notes}")
        
        has_notes = any(step.notes for step in analyzed_sop.steps)
        self.assertTrue(has_notes, "SOP 分析未能提取备注 (Notes)。")
        print(f"     [OK] 备注提取验证通过。")
        
        print("\n[结果] SOP 混合分析逻辑验证通过。")

if __name__ == "__main__":
    unittest.main()
