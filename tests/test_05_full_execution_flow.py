
import sys
import os
import unittest
from unittest.mock import patch

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "../backend")))

from src.core.contextStruct import SOP, Step
from src.agents import Dispatcher
from fastapi.testclient import TestClient
import backend.api_bridge as api_bridge

"""
完整执行流与 API 接口测试脚本 (Test 05)
验证 Dispatcher 的执行逻辑（包括变量引用和记忆流转）以及后端 API 接口的可用性。
"""

@patch("src.core.llm.llm_client")
class TestFullExecutionFlow(unittest.TestCase):
    def test_dispatcher_flow(self, mock_llm):
        print("\n[测试 05] 执行器与记忆流测试")

        step1 = Step(
            id="calc_sum",
            name="计算加和",
            tool="calculator",
            inputs={"expression": "2 + 3"},
            outputs={"sum": "result"}
        )
        step2 = Step(
            id="calc_total",
            name="计算总值",
            tool="calculator",
            inputs={"expression": "${sum} * 10"},
            outputs={"total": "result"}
        )
        step3 = Step(
            id="smart_calc",
            name="智能计算",
            tool="calculator",
            inputs={"expression": "表达式"},
            notes="需要推导表达式",
            analysis_status="analyzed"
        )

        mock_llm.chat.return_value = '{"action": "execute_tool", "tool": "calculator", "inputs": {"expression": "6 * 7"}}'

        sop = SOP(id="test_flow", description="dispatcher flow", steps=[step1, step2, step3])
        dispatcher = Dispatcher()

        print("  -> 步骤 1: 运行 SOP")
        final_context = dispatcher.run(sop, {"user_query": "计算测试"})

        print("  -> 步骤 2: 验证上下文")
        self.assertEqual(final_context.get("sum"), 5)
        self.assertEqual(final_context.get("total"), 50)
        self.assertGreaterEqual(len(dispatcher.memory.history), 2)

    def test_api_bridge_endpoints(self, mock_llm):
        print("\n[测试 05] API Bridge 接口测试")
        mock_llm.chat.return_value = '{"sop_id": "航道通航底高程", "args": {"DWT": "50000"}}'
        client = TestClient(api_bridge.app)

        print("  -> 步骤 1: 获取模型配置")
        resp = client.get("/llm_configs")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(isinstance(resp.json(), list))

        print("  -> 步骤 2: 获取 SOP 列表")
        resp = client.get("/sops")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(isinstance(resp.json(), list))

        print("  -> 步骤 3: 获取测试源码")
        resp = client.get("/test_source/1")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("content", resp.json())

        print("  -> 步骤 4: 执行聊天接口")
        resp = client.post("/chat", json={"query": "计算5万吨级油轮的航道通航底高程"})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data.get("sop_id"), "航道通航底高程")

if __name__ == "__main__":
    unittest.main()
