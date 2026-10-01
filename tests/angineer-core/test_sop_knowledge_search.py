"""SOP knowledge_search 重定向 canonical 检索的单测。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/engtools/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from angineer_core.base_contracts import SOP, Step  # noqa: E402
from angineer_core.sop_runner import SopRunner  # noqa: E402


def make_search_sop():
    return SOP(
        id="sop-ks",
        name_zh="检索SOP",
        steps=[
            Step(
                id="s1",
                name_zh="检索",
                tool="knowledge_search",
                inputs={"query": "通航宽度"},
                outputs={"evidence": "result"},
            )
        ],
    )


class SopKnowledgeSearchCanonicalTests(unittest.TestCase):
    """knowledge_search 步骤必须走 canonical 检索，不触碰 engtool registry。"""

    def test_canonical_impl_called_with_runner_scope(self):
        runner = SopRunner(llm_client=Mock(), library_id="lib-x", doc_ids=["d1"])
        with patch(
            "angineer_core.agent_tools._run_knowledge_search_impl",
            return_value={"items": [{"text": "证据A"}, {"text": "证据B"}], "total": 2},
        ) as impl:
            blackboard = runner.run_sop(make_search_sop(), {"user_query": "查通航宽度"})
        impl.assert_called_once()
        kwargs = impl.call_args.kwargs
        self.assertEqual(kwargs["query"], "通航宽度")
        self.assertEqual(kwargs["library_id"], "lib-x")
        self.assertEqual(kwargs["doc_ids"], ["d1"])
        self.assertEqual(blackboard["evidence"], "证据A\n\n证据B")
        self.assertEqual(runner.memory.history[0].status, "success")

    def test_default_scope_when_not_injected(self):
        runner = SopRunner(llm_client=Mock())
        with patch(
            "angineer_core.agent_tools._run_knowledge_search_impl",
            return_value={"items": [{"text": "证据"}], "total": 1},
        ) as impl:
            runner.run_sop(make_search_sop(), {})
        kwargs = impl.call_args.kwargs
        self.assertEqual(kwargs["library_id"], "default")
        self.assertIsNone(kwargs["doc_ids"])

    def test_canonical_error_passes_through_without_legacy_fallback(self):
        runner = SopRunner(llm_client=Mock())
        with patch(
            "angineer_core.agent_tools._run_knowledge_search_impl",
            return_value={"error": "本地知识检索不可用（端口未注册）"},
        ):
            runner.run_sop(make_search_sop(), {})
        self.assertEqual(runner.memory.history[0].status, "failed")
        self.assertIn("不可用", runner.memory.history[0].error)


if __name__ == "__main__":
    unittest.main()
