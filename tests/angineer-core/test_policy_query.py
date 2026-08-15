"""P7 终态查询入口单测：policy 路径返回与旧 /api/query 兼容的结构。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig  # noqa: E402
from angineer_core.agent_tools import AgentTool  # noqa: E402
from agent_test_utils import MockLLM, text_events, tool_block  # noqa: E402


def _make_tool():
    def handler(query: str = "x", **kwargs):
        return {
            "items": [{
                "item_id": "a",
                "entity_type": "content",
                "doc_id": "d1",
                "title": "t",
                "text": "证据文本",
                "score": 0.9,
                "metadata": {"doc_title": "船闸规范.pdf", "section_path": "2.2 级别划分", "cite": "K1"},
            }],
            "citations": [{
                "target_id": "a",
                "doc_id": "d1",
                "doc_title": "船闸规范.pdf",
                "page_idx": 0,
                "section_path": "2.2 级别划分",
                "snippet": "证据文本",
                "score": 0.9,
                "marker": "K1",
            }],
        }

    return AgentTool(
        name="knowledge_search",
        description="检索",
        parameters_schema={"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
        handler=handler,
        read_only=True,
    )


def _intent(level="L1", service_mode="semantic_retrieval"):
    return SimpleNamespace(
        intent_level=level, primary_level=level, intent_type="concept_resolution",
        service_mode=service_mode, reason="规则命中",
        execution_plan=[service_mode], final_path=service_mode,
        parameters={}, required_capabilities=["retrieval"], matched_sop=None,
        fallback_reason=None, attempted_paths=[],
    )


class PolicyQueryTests(unittest.TestCase):
    def _run(self, llm, attempts, intent_result=None, **kwargs):
        from angineer_core.policy_query import run_policy_query

        with patch("angineer_core.classifier.IntentClassifier") as classifier_cls:
            classifier_cls.return_value.classify_intent.return_value = intent_result or _intent()
            with patch("angineer_core.policy_query._load_doc_nodes", return_value=[]):
                with patch("ai_inference.llm_client.get_llm_client", return_value=llm):
                    with patch("angineer_core.agent_policy.build_attempts", return_value=attempts):
                        return run_policy_query("测试问题", **kwargs)

    def test_policy_query_returns_legacy_compatible_shape(self):
        llm = MockLLM(lambda messages, kwargs: (
            text_events(tool_block([{"name": "knowledge_search", "arguments": {"query": "测试问题"}}]))
            if len(llm.calls) == 1 else text_events("答案 [K1]")
        ))
        attempt = AttemptConfig(
            name="L1 语义检索",
            config_factory=lambda: AgentLoopConfig(
                llm=llm, tools=[_make_tool()], system_prompt="p", max_turns=2,
            ),
            requires_tools=True,
        )
        result = self._run(llm, [attempt])

        self.assertNotIn("error", result)
        self.assertTrue(result["query_id"].startswith("q-"))
        self.assertEqual(result["intent"]["intent_level"], "L1")
        self.assertEqual(result["answer"], "答案 [K1]")
        self.assertEqual(result["retrieved_items"][0]["item_id"], "a")
        self.assertEqual(result["citations"][0]["marker"], "K1")
        self.assertIsNone(result["sql"])
        self.assertFalse(result["fallback_used"])
        self.assertTrue(result["strategy"])
        self.assertIn("intent", result["stage_timings"])
        self.assertIn("agent_loop", result["stage_timings"])
        self.assertEqual(result["sop_trace"], [])
        self.assertGreaterEqual(result["latency_ms"], 0)
        self.assertIn("route_debug", result)
        self.assertIn("retrieval_debug", result)

    def test_policy_query_marks_fallback_used(self):
        llm = MockLLM(lambda messages, kwargs: text_events("第一段" if len(llm.calls) == 1 else "第二段答案"))
        first = AttemptConfig(
            name="L2 条款/表格定位",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
            success_check=lambda added: False,
            fallback_note="L2 未命中，回退 L1",
        )
        second = AttemptConfig(
            name="L1 语义检索",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
        )
        result = self._run(llm, [first, second])
        self.assertEqual(result["answer"], "第二段答案")
        self.assertTrue(result["fallback_used"])

    def test_policy_query_returns_error_on_failure(self):
        from angineer_core.policy_query import run_policy_query

        with patch("angineer_core.classifier.IntentClassifier") as classifier_cls:
            classifier_cls.return_value.classify_intent.return_value = _intent()
            with patch("angineer_core.agent_policy.build_attempts", side_effect=RuntimeError("boom")):
                with patch("angineer_core.policy_query._load_doc_nodes", return_value=[]):
                    result = run_policy_query("测试问题")
        self.assertIn("error", result)


if __name__ == "__main__":
    unittest.main()
