
import sys
import os
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.src.core.sop_loader import SopLoader
from backend.src.agents import IntentClassifier

@patch("src.agents.classifier.llm_client")
class TestIntentClassifier(unittest.TestCase):
    def test_route_success(self, mock_llm):
        print("\n[测试 02] 意图分类器路由测试")
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        print("  -> 步骤 1: 加载 SOP 列表")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()
        self.assertGreater(len(sops), 0)

        query = "计算5万吨级油轮的航道通航底高程"
        mock_response = '{"sop_id": "航道通航底高程", "args": {"DWT": "50000", "ship_type": "oil_tanker"}}'
        mock_llm.chat.return_value = mock_response

        print("  -> 步骤 2: 执行路由")
        classifier = IntentClassifier(sops)
        sop, args = classifier.route(query)

        print("  -> 步骤 3: 验证结果")
        self.assertIsNotNone(sop)
        self.assertEqual(sop.id, "航道通航底高程")
        self.assertTrue(isinstance(args, dict))
        print(f"     路由 SOP: {sop.id}")
        print(f"     参数: {args}")

    def test_route_none(self, mock_llm):
        print("\n[测试 02] 意图分类器无匹配测试")
        sop_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend", "sops")
        loader = SopLoader(sop_dir)
        sops = loader.load_all()

        query = "随便聊聊"
        mock_llm.chat.return_value = "```json\n{\"sop_id\": null, \"reason\": \"none\", \"args\": {}}\n```"

        print("  -> 步骤 1: 执行路由")
        classifier = IntentClassifier(sops)
        sop, args = classifier.route(query)

        print("  -> 步骤 2: 验证无匹配")
        self.assertIsNone(sop)
        self.assertEqual(args, {})

if __name__ == "__main__":
    unittest.main()
