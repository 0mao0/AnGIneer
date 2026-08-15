"""阶段 2c 测试：evals 链路 scope 落盘——policy_query 返回与 answer_eval prediction 均带 scope。"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../angineer-core")))

from agent_test_utils import MockLLM, text_events  # noqa: E402


def _intent():
    return SimpleNamespace(
        intent_level="L1", primary_level="L1", intent_type="concept_resolution",
        service_mode="semantic_retrieval", reason="规则命中",
        execution_plan=["semantic_retrieval"], final_path="semantic_retrieval",
        parameters={}, required_capabilities=["retrieval"], matched_sop=None,
        fallback_reason=None, attempted_paths=[],
    )


class PolicyQueryScopeTests(unittest.TestCase):
    def test_run_policy_query_returns_scope(self):
        from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig
        from angineer_core.policy_query import run_policy_query

        llm = MockLLM(lambda messages, kwargs: text_events("答案 [K1]", "stop"))
        attempt = AttemptConfig(
            name="L1 语义检索",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[], system_prompt="p", max_turns=1),
        )

        with patch("angineer_core.classifier.IntentClassifier") as classifier_cls, \
             patch("angineer_core.policy_query._load_doc_nodes", return_value=[]), \
             patch("ai_inference.llm_client.get_llm_client", return_value=llm), \
             patch("angineer_core.agent_policy.build_attempts", return_value=[attempt]):
            classifier_cls.return_value.classify_intent.return_value = _intent()
            result = run_policy_query("测试问题", library_id="lib-x", doc_ids=["d1"])

        self.assertNotIn("error", result)
        self.assertEqual(result["scope"]["library_id"], "lib-x")
        self.assertEqual(result["scope"]["doc_ids"], ["d1"])


class AnswerEvalScopeTests(unittest.TestCase):
    def test_prediction_carries_scope(self):
        from evals_core.runner.answer_eval import AnswerEvaluator

        evaluator = AnswerEvaluator()
        question = {"id": "q1", "question": "测试", "library_id": "lib-x", "doc_ids": ["d1"]}
        data = {
            "answer": "答案",
            "scope": {"library_id": "lib-x", "doc_ids": ["d1"]},
        }
        with patch("evals_core.runner.answer_eval.run_eval_query", return_value=data):
            result = evaluator.run_prediction(question)

        prediction = result.get("prediction") or result
        self.assertEqual(prediction["scope"]["library_id"], "lib-x")
        self.assertEqual(prediction["scope"]["doc_ids"], ["d1"])


if __name__ == "__main__":
    unittest.main()
