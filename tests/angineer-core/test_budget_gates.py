"""P4.3 预算闸门：make_budget_transformer / make_budget_stopper 单元测试。"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import (  # noqa: E402
    make_budget_stopper,
    make_budget_transformer,
)
from angineer_core.agent_loop import TurnContext  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402


def estimate(messages):
    return sum(len(m.content or "") for m in messages) // 2


class BudgetTransformerTests(unittest.TestCase):
    def test_under_budget_leaves_messages_unchanged(self):
        messages = [
            AgentMessage(role="user", content="问题"),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 200, meta={"items": [], "total": 0}),
        ]
        transformer = make_budget_transformer(max_tokens_est=1000)
        out = transformer(messages)
        self.assertIs(out, messages)
        self.assertEqual(out[1].content, "K" * 200)

    def test_over_budget_compresses_oldest_first(self):
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1}),
            AgentMessage(role="tool", name="table_search", content="T" * 5000, meta={"items": [], "total": 0}),
        ]
        transformer = make_budget_transformer(max_tokens_est=2000)
        out = transformer(messages)
        self.assertLessEqual(estimate(out), 2000)
        self.assertTrue(out[1].content.startswith("[已压缩: 工具 knowledge_search 的结果"))
        self.assertTrue(out[2].content.startswith("[已压缩: 工具 table_search 的结果"))
        self.assertIn("检索到 1 条候选", out[1].content)

    def test_projection_does_not_mutate_history(self):
        """2026-09-24 投影式改造：压缩只作用于返回的副本，原消息列表/对象不动。"""
        original_tool = AgentMessage(
            role="tool", name="knowledge_search",
            content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1},
        )
        messages = [AgentMessage(role="user", content="Q" * 1000), original_tool]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)

        self.assertTrue(out[1].content.startswith("[已压缩:"))
        self.assertEqual(original_tool.content, "K" * 5000)  # 本体未被改写
        self.assertIsNot(out, messages)
        self.assertIsNot(out[1], original_tool)
        self.assertNotIn("_budget_summary", original_tool.meta)  # 摘要不再写进 meta

    def test_summary_cached_across_calls(self):
        """闭包缓存：同一批消息对象重复 transform，结果一致（摘要不重复计算）。"""
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(role="tool", name="knowledge_search", content="K" * 5000, meta={"items": [{"item_id": "i1"}], "total": 1}),
        ]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)
        out2 = transformer(messages)
        self.assertEqual(out2[1].content, out[1].content)
        self.assertIn("检索到 1 条候选", out2[1].content)

    def test_sop_raw_summary_counts_successful_steps(self):
        messages = [
            AgentMessage(role="user", content="Q" * 1000),
            AgentMessage(
                role="tool",
                name="sop_execute",
                content="x" * 5000,
                meta={
                    "sop_id": "sop-1",
                    "sop_trace": [
                        {"step_id": "s1", "status": "success"},
                        {"step_id": "s2", "status": "failed"},
                    ],
                },
            ),
        ]
        transformer = make_budget_transformer(max_tokens_est=100)
        out = transformer(messages)
        self.assertIn("SOP sop-1 执行 2 步，成功 1 步", out[1].content)


class BudgetStopperTests(unittest.TestCase):
    def test_stops_when_over_threshold(self):
        stopper = make_budget_stopper(threshold=500)
        context = TurnContext(
            turn=2,
            messages=[AgentMessage(role="tool", content="X" * 2000)],
            tool_results=[],
            usage={},
        )
        self.assertTrue(stopper(context))

    def test_does_not_stop_under_threshold(self):
        stopper = make_budget_stopper(threshold=500)
        context = TurnContext(
            turn=1,
            messages=[AgentMessage(role="tool", content="x" * 100)],
            tool_results=[],
            usage={},
        )
        self.assertFalse(stopper(context))


if __name__ == "__main__":
    unittest.main()
