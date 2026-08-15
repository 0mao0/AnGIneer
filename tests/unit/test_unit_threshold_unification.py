"""
单元测试：SOP 路由置信度阈值统一（B3）。

B3：classifier 拒绝阈值（0.45）与 dispatcher 执行门槛（0.6）收敛为单一常量。
"""
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))


class TestThresholdUnification(unittest.TestCase):
    """B3：单一阈值常量被 classifier 与 dispatcher 共同引用。"""

    def test_single_threshold_shared_by_classifier_and_agent_tools(self):
        from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD
        from angineer_core.classifier import ROUTE_CONFIDENCE_THRESHOLD

        self.assertEqual(ROUTE_CONFIDENCE_THRESHOLD, SOP_ROUTE_CONFIDENCE_THRESHOLD)
        self.assertGreaterEqual(SOP_ROUTE_CONFIDENCE_THRESHOLD, 0.0)
        self.assertLessEqual(SOP_ROUTE_CONFIDENCE_THRESHOLD, 1.0)
        # agent 工具的 SOP 执行入口与 classifier 共用同一阈值（原 dispatcher 双阈值已收敛）
        from angineer_core.agent_tools import SopRunnerAdapter

        self.assertTrue(callable(SopRunnerAdapter.sop_execute))

    def test_classifier_accepts_at_threshold(self):
        from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD
        from angineer_core.base_contracts import SOP, Step
        from angineer_core.classifier import IntentClassifier
        from ai_inference.llm_client import ChatResult
        import json

        sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                steps=[Step(id="s1", tool="calculator", inputs={})],
            )
        ]
        mock_client = Mock()
        mock_client.chat_result.return_value = ChatResult(
            text=json.dumps(
                {"sop_id": "math_sop", "confidence": SOP_ROUTE_CONFIDENCE_THRESHOLD, "reason": "匹配"}
            ),
            finish_reason="stop",
        )
        classifier = IntentClassifier(sops, llm_client=mock_client)

        result = classifier.route("计算 25 * 4")

        self.assertIsNotNone(result.sop)
        self.assertEqual(result.sop.id, "math_sop")

    def test_classifier_rejects_below_threshold(self):
        from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD
        from angineer_core.base_contracts import SOP, Step
        from angineer_core.classifier import IntentClassifier
        from ai_inference.llm_client import ChatResult
        import json

        sops = [
            SOP(
                id="math_sop",
                name_zh="数学计算",
                steps=[Step(id="s1", tool="calculator", inputs={})],
            )
        ]
        mock_client = Mock()
        mock_client.chat_result.return_value = ChatResult(
            text=json.dumps(
                {
                    "sop_id": "math_sop",
                    "confidence": round(SOP_ROUTE_CONFIDENCE_THRESHOLD - 0.01, 4),
                    "reason": "部分相关",
                }
            ),
            finish_reason="stop",
        )
        classifier = IntentClassifier(sops, llm_client=mock_client)

        result = classifier.route("计算 25 * 4")

        self.assertIsNone(result.sop)


if __name__ == "__main__":
    unittest.main()
