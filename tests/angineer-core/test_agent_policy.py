"""P7 策略层单测：IntentResult → Attempt 列表 / 路由 note。"""
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_policy import build_attempts, format_route_note  # noqa: E402


class PolicyTests(unittest.TestCase):
    def _intent(self, level, service_mode):
        from types import SimpleNamespace

        return SimpleNamespace(
            intent_level=level, primary_level=level, intent_type="x",
            service_mode=service_mode, reason="规则命中",
            execution_plan=[service_mode], final_path=service_mode,
            parameters={}, required_capabilities=[], matched_sop=None,
            fallback_reason=None, attempted_paths=[],
        )

    def test_l2_returns_two_attempts_with_fallback_note(self):
        attempts = build_attempts(
            intent_result=self._intent("L2", "sql_first"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: Mock(),
        )
        self.assertEqual([a.name for a in attempts], ["L2 条款/表格定位", "L1 语义检索"])
        self.assertIn("回退", attempts[0].fallback_note)
        self.assertTrue(all(a.requires_tools for a in attempts))

    def test_l1_single_attempt(self):
        attempts = build_attempts(
            intent_result=self._intent("L1", "semantic_retrieval"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: Mock(),
        )
        self.assertEqual(len(attempts), 1)
        self.assertEqual(attempts[0].name, "L1 语义检索")
        self.assertTrue(attempts[0].requires_tools)

    def test_answer_usable_rejects_paraphrased_refusal(self):
        """模型自拟拒答（非标准话术）也必须被成功检查识别，不能当作成功答案放行。"""
        from angineer_core.agent_messages import AgentMessage
        from angineer_core.agent_policy import _answer_usable

        self.assertFalse(_answer_usable([
            AgentMessage(role="assistant", content="没有检索到足够证据支持最终结论，不要自行补全。"),
        ]))
        self.assertFalse(_answer_usable([
            AgentMessage(role="assistant", content="没有检索到足够证据支持最终结论。"),
        ]))
        self.assertTrue(_answer_usable([
            AgentMessage(role="assistant", content="原文提到集成 17 类算法、12 个模型，但未列出具体名称。"),
        ]))

    def test_l0_single_chat_attempt(self):
        attempts = build_attempts(
            intent_result=self._intent("L0", "casual_chat"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: Mock(),
        )
        self.assertEqual([a.name for a in attempts], ["L0 闲聊直答"])
        self.assertFalse(attempts[0].requires_tools)

    def test_l3_l4_uses_complex_attempt(self):
        attempts = build_attempts(
            intent_result=self._intent("L4", "dynamic_orchestration"),
            scene="docs", library_id="default", doc_ids=[],
            load_nodes=lambda: [], llm_factory=lambda: Mock(),
        )
        self.assertEqual([a.name for a in attempts], ["L3/L4 复杂任务"])
        self.assertTrue(attempts[0].requires_tools)

    def test_format_route_note(self):
        note = format_route_note(self._intent("L1", "semantic_retrieval"))
        self.assertTrue(note.startswith("意图判断：正文问答（L1）→ 策略 semantic_retrieval"))
        self.assertIn("规则命中", note)
        self.assertIsNone(format_route_note(None))


if __name__ == "__main__":
    unittest.main()
