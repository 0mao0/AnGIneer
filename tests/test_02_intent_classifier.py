
import sys
import os
import unittest
from unittest.mock import patch

# 将项目根目录添加到路径中
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader
from backend.src.agents import IntentClassifier

@patch("backend.src.core.llm.llm_client")
class TestIntentClassifier(unittest.TestCase):
    """测试分类器是否能根据用户查询正确识别 SOP。"""
    
    def test_run(self, mock_llm):
        print("\n[测试 02] 正在启动意图分类器路由测试...")
        
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        print(f"  -> 步骤 1: 加载 SOP 库从目录: {sop_dir}")
        print(f"     [CALL] src/core/sop_loader.py -> SopLoader.load_all()")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()
        print(f"     [OK] 已加载 {len(sops)} 个 SOP 模板。")
        
        query = "计算5万吨级油轮的航道通航底高程"
        print(f"  -> 步骤 2: 模拟用户输入: \"{query}\"")
        
        # 模拟分类器 LLM 响应
        mock_response = '{"sop_id": "航道通航底高程", "args": {"DWT": "50000", "ship_type": "oil_tanker"}}'
        mock_llm.chat.return_value = mock_response
        print(f"  -> 步骤 3: 模拟 LLM 路由响应: {mock_response}")
        
        classifier = IntentClassifier(sops)
        print(f"     [CALL] src/agents/intent_classifier.py -> IntentClassifier.route()")
        sop, args = classifier.route(query)
        
        print("  -> 步骤 4: 验证路由结果...")
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "航道通航底高程")
        print(f"     [OK] 成功路由至 SOP: {sop.id}")
        print(f"     [OK] 成功提取参数: {args}")
        
        print("\n[结果] 意图分类器逻辑验证通过。")

if __name__ == "__main__":
    unittest.main()
