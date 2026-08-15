"""阶段 3a 测试：Evidence 统一证据模型落地——检索工具返回 evidences，policy_query 与 evals 透传。"""
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

from agent_test_utils import MockLLM, text_events, tool_block  # noqa: E402
from angineer_core.agent_tools import AgentTool, RetrieverAdapter  # noqa: E402
from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402


class _FakeRetriever:
    def __init__(self, items):
        self._items = items

    def retrieve(self, *args, **kwargs):
        return list(self._items)


def _make_item(item_id="a", text="正文证据", doc_id="d1"):
    return RetrievedItem(
        item_id=item_id,
        entity_type="chunk",
        doc_id=doc_id,
        title="条文",
        text=text,
        score=0.9,
        metadata={"page_idx": 3, "section_path": "第1章"},
    )


def _intent():
    return SimpleNamespace(
        intent_level="L1", primary_level="L1", intent_type="concept_resolution",
        service_mode="semantic_retrieval", reason="规则命中",
        execution_plan=["semantic_retrieval"], final_path="semantic_retrieval",
        parameters={}, required_capabilities=["retrieval"], matched_sop=None,
        fallback_reason=None, attempted_paths=[],
    )


class KnowledgeSearchEvidenceTests(unittest.TestCase):
    def test_knowledge_search_returns_evidences(self):
        tool = RetrieverAdapter.knowledge_search(
            library_id="lib-ev",
            dense=_FakeRetriever([_make_item()]),
            sparse=_FakeRetriever([]),
            clause=_FakeRetriever([]),
        )
        result = tool.handler(query="测试")

        self.assertIn("items", result)
        self.assertEqual(result["items"][0]["item_id"], "a")
        evidences = result["evidences"]
        self.assertEqual(len(evidences), 1)
        ev = evidences[0]
        self.assertEqual(ev["kind"], "text")
        self.assertEqual(ev["evidence_id"], "a")
        self.assertEqual(ev["doc_id"], "d1")
        self.assertEqual(ev["doc_title"], "条文")
        self.assertEqual(ev["content"], "正文证据")
        self.assertEqual(ev["page_idx"], 3)
        self.assertEqual(ev["section_path"], "第1章")
        self.assertGreater(ev["score"], 0.0)
        self.assertEqual(ev["source"], "knowledge_search")
        self.assertEqual(ev["library_id"], "lib-ev")


class TableSearchEvidenceTests(unittest.TestCase):
    def test_table_search_returns_evidences(self):
        tool = RetrieverAdapter.table_search(
            library_id="lib-ev",
            table=_FakeRetriever([_make_item(item_id="t1", text="表格内容")]),
            formula=_FakeRetriever([]),
        )
        result = tool.handler(query="表格")

        self.assertIn("items", result)
        ev = result["evidences"][0]
        self.assertEqual(ev["kind"], "table")
        self.assertEqual(ev["evidence_id"], "t1")
        self.assertEqual(ev["source"], "table_search")
        self.assertEqual(ev["library_id"], "lib-ev")


class EntitySearchEvidenceTests(unittest.TestCase):
    def test_entity_search_returns_graph_evidences(self):
        entity = Mock()
        entity.model_dump.return_value = {"name": "系缆力", "layer": "concept"}

        tool = RetrieverAdapter.entity_search(library_id="lib-ev")
        with patch("docs_core.step07_graph.graph_store.GraphStore") as store_cls:
            store_cls.return_value.search_entities.return_value = [entity]
            result = tool.handler(query="系缆力")

        ev = result["evidences"][0]
        self.assertEqual(ev["kind"], "graph_entity")
        self.assertEqual(ev["evidence_id"], "系缆力")
        self.assertEqual(ev["source"], "graph")
        self.assertEqual(ev["library_id"], "lib-ev")

    def test_entity_search_fallback_merges_evidences(self):
        fallback_ev = {
            "evidence_id": "a", "kind": "text", "doc_id": "d1",
            "content": "正文证据", "library_id": "lib-ev", "source": "knowledge_search",
        }
        tool = RetrieverAdapter.entity_search(library_id="lib-ev")
        with patch("docs_core.step07_graph.graph_store.GraphStore") as store_cls, \
             patch("angineer_core.agent_tools._run_knowledge_search",
                   return_value={"items": [], "citations": [], "evidences": [fallback_ev]}):
            store_cls.return_value.search_entities.return_value = []
            result = tool.handler(query="查无此实体")

        self.assertEqual(result["evidences"], [fallback_ev])


class PolicyQueryEvidenceTests(unittest.TestCase):
    def test_run_policy_query_returns_evidences(self):
        from angineer_core.agent_loop import AgentLoopConfig, AttemptConfig
        from angineer_core.policy_query import run_policy_query

        ev = {
            "evidence_id": "a", "kind": "text", "doc_id": "d1",
            "content": "正文证据", "library_id": "default", "source": "knowledge_search",
        }
        tool = AgentTool(
            name="knowledge_search",
            description="d",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
            },
            handler=lambda query=None, **kwargs: {"items": [{"item_id": "a"}], "evidences": [ev]},
        )
        llm = MockLLM(lambda messages, kwargs: (
            text_events(tool_block([{"name": "knowledge_search", "arguments": {"query": "q"}}]))
            if len(llm.calls) == 1 else text_events("答案 [K1]")
        ))
        attempt = AttemptConfig(
            name="L1 语义检索",
            config_factory=lambda: AgentLoopConfig(llm=llm, tools=[tool], system_prompt="p", max_turns=3),
        )

        with patch("angineer_core.classifier.IntentClassifier") as classifier_cls, \
             patch("angineer_core.policy_query._load_doc_nodes", return_value=[]), \
             patch("ai_inference.llm_client.get_llm_client", return_value=llm), \
             patch("angineer_core.agent_policy.build_attempts", return_value=[attempt]):
            classifier_cls.return_value.classify_intent.return_value = _intent()
            result = run_policy_query("测试问题")

        self.assertNotIn("error", result)
        self.assertEqual(result["evidences"][0]["evidence_id"], "a")
        self.assertEqual(result["retrieved_items"][0]["item_id"], "a")


class AnswerEvalEvidenceTests(unittest.TestCase):
    def test_prediction_carries_evidences(self):
        from evals_core.runner.answer_eval import AnswerEvaluator

        evaluator = AnswerEvaluator()
        question = {"id": "q1", "question": "测试"}
        data = {"answer": "答案", "evidences": [{"evidence_id": "a", "kind": "text"}]}
        with patch("evals_core.runner.answer_eval.run_eval_query", return_value=data):
            result = evaluator.run_prediction(question)

        prediction = result.get("prediction") or result
        self.assertEqual(prediction["evidences"][0]["evidence_id"], "a")


if __name__ == "__main__":
    unittest.main()
