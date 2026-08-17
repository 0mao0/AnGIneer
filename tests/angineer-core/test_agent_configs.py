"""P3.1 build_qa_config 装配单测。"""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import (  # noqa: E402
    QA_AGENT_SYSTEM_PROMPT,
    build_chat_config,
    build_qa_config,
    make_final_answer_guard,
)
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.agent_tools import MarkerAllocator, _assign_cites  # noqa: E402
from docs_core.step09_query.protocols.contracts import RetrievedItem  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402


class QaConfigTests(unittest.TestCase):
    def test_build_qa_config_assembles_three_readonly_tools(self):
        config = build_qa_config(
            llm=Mock(),
            doc_nodes=[],
            library_id="default",
            doc_ids=["doc-1"],
            task_type="definition_qa",
        )
        self.assertEqual([tool.name for tool in config.tools], [
            "knowledge_search",
            "table_search",
            "entity_search",
        ])
        self.assertTrue(all(tool.read_only for tool in config.tools))
        self.assertEqual(config.max_turns, 3)
        self.assertIsInstance(config.codec, TextToolCallCodec)
        self.assertIn("检索证据", config.system_prompt)
        self.assertIn("没有检索到足够证据", config.system_prompt)

    def test_custom_tools_override(self):
        tool = Mock(name="custom_tool")
        config = build_qa_config(llm=Mock(), tools=[tool], max_turns=5)
        self.assertEqual(config.tools, [tool])
        self.assertEqual(config.max_turns, 5)

    def test_followup_rule_appended_when_env_true(self):
        with patch.dict(os.environ, {"ANGINEER_FOLLOWUP_QUESTION": "true"}, clear=False):
            config = build_qa_config(llm=Mock())
        self.assertIn("末尾追问规则", config.system_prompt)
        self.assertIs(config.followup_question, True)

    def test_followup_rule_absent_when_env_false(self):
        with patch.dict(os.environ, {"ANGINEER_FOLLOWUP_QUESTION": "false"}, clear=False):
            config = build_qa_config(llm=Mock())
        self.assertEqual(config.system_prompt, QA_AGENT_SYSTEM_PROMPT)
        self.assertIs(config.followup_question, False)

    def test_followup_defaults_on_and_explicit_param_wins(self):
        with patch.dict(os.environ, {}, clear=False):
            config_default = build_qa_config(llm=Mock())
        self.assertTrue(config_default.followup_question)
        config_off = build_qa_config(llm=Mock(), followup_question=False)
        self.assertFalse(config_off.followup_question)
        self.assertEqual(config_off.system_prompt, QA_AGENT_SYSTEM_PROMPT)

    def test_guard_appends_followup_question_on_refusal_when_enabled(self):
        from angineer_core.agent_messages import REFUSAL_FOLLOWUP_QUESTION

        guard = make_final_answer_guard(enforce_evidence=True, followup_question=True)
        added = [
            AgentMessage(role="tool", content='{"items": []}', is_error=False),
            AgentMessage(role="assistant", content="测试答案"),
        ]
        result = guard(added)
        self.assertIsNotNone(result)
        answer, _note = result
        self.assertIn(REFUSAL_FOLLOWUP_QUESTION, answer)

    def test_guard_refusal_plain_when_disabled(self):
        from angineer_core.qa_pipeline import REFUSAL_ANSWER_TEXT

        guard = make_final_answer_guard(enforce_evidence=True, followup_question=False)
        added = [
            AgentMessage(role="tool", content='{"items": []}', is_error=False),
            AgentMessage(role="assistant", content="测试答案"),
        ]
        result = guard(added)
        self.assertIsNotNone(result)
        answer, _note = result
        self.assertEqual(answer, REFUSAL_ANSWER_TEXT)

    def test_knowledge_search_and_table_search_use_separate_task_types(self):
        captured = {}

        def fake_knowledge(**kwargs):
            captured["knowledge"] = kwargs
            return Mock(name="knowledge_tool")

        def fake_table(**kwargs):
            captured["table"] = kwargs
            return Mock(name="table_tool")

        with patch(
            "angineer_core.agent_configs.RetrieverAdapter.knowledge_search",
            side_effect=fake_knowledge,
        ), patch(
            "angineer_core.agent_configs.RetrieverAdapter.table_search",
            side_effect=fake_table,
        ):
            build_qa_config(
                llm=Mock(),
                task_type="table_qa",
                knowledge_task_type="content_qa",
            )
        self.assertEqual(captured["knowledge"]["task_type"], "content_qa")
        # table_search 内部固定走 table_qa，不需要外部传入 task_type
        self.assertNotIn("task_type", captured["table"])

    def test_inline_citations_appended_to_prompt(self):
        config = build_qa_config(
            llm=Mock(),
            inline_citations=[
                {
                    "label": "S1",
                    "reference": {"docTitle": "规范A", "content": "5.4.12 条内容"},
                }
            ],
        )
        self.assertIn("规范A", config.system_prompt)
        self.assertIn("显式引用证据", config.system_prompt)

    def test_system_prompt_constant_documented(self):
        self.assertTrue(QA_AGENT_SYSTEM_PROMPT.startswith("你是一个工程规范领域"))

    def test_build_chat_config_has_no_tools(self):
        config = build_chat_config(llm=Mock())
        self.assertEqual(config.tools, [])
        self.assertEqual(config.max_turns, 1)
        self.assertIsInstance(config.codec, TextToolCallCodec)

    def test_cite_markers_assigned(self):
        items = [RetrievedItem(item_id="a", entity_type="content", doc_id="d",
                                title="t", text="x", score=1.0, metadata={}),
                 RetrievedItem(item_id="b", entity_type="content", doc_id="d",
                               title="t", text="y", score=1.0, metadata={})]
        allocator = MarkerAllocator()
        _assign_cites(items, allocator, "K")
        self.assertEqual(items[0].metadata["cite"], "K1")
        self.assertEqual(items[1].metadata["cite"], "K2")

    def test_allocator_unique_across_calls(self):
        allocator = MarkerAllocator()
        first = [RetrievedItem(item_id="a", entity_type="content", doc_id="d",
                               title="t", text="x", score=1.0, metadata={})]
        second = [RetrievedItem(item_id="b", entity_type="content", doc_id="d",
                                title="t", text="y", score=1.0, metadata={})]
        _assign_cites(first, allocator, "K")
        _assign_cites(second, allocator, "K")
        self.assertEqual(first[0].metadata["cite"], "K1")
        self.assertEqual(second[0].metadata["cite"], "K2")

    def test_qa_config_installs_guard_even_without_enforce_evidence(self):
        config = build_qa_config(llm=Mock(), enforce_evidence=False)
        self.assertIsNotNone(config.final_answer_guard)

    def test_build_qa_config_accepts_marker_allocator(self):
        config = build_qa_config(llm=Mock(), marker_allocator=MarkerAllocator())
        self.assertEqual([tool.name for tool in config.tools], [
            "knowledge_search",
            "table_search",
            "entity_search",
        ])

    def test_guard_removes_invalid_markers(self):
        guard = make_final_answer_guard(enforce_evidence=False)
        added = [AgentMessage(role="tool", content='{"items": [{"item_id":"a","text":"x","metadata":{"cite":"K1"}}]}')]
        new_answer, note = guard([*added, AgentMessage(role="assistant", content="依据 [K1] 和 [K9] 作答")])
        self.assertNotIn("[K9]", new_answer)
        self.assertIn("无效引用标记", note)

    def test_guard_strips_markers_without_tool_messages(self):
        """模型没调工具却输出 [Kx] 时，视为编造标记并清理，但不强制拒答。"""
        guard = make_final_answer_guard(enforce_evidence=True)
        new_answer, note = guard([AgentMessage(role="assistant", content="航道水深由吃水加富裕深度确定 [K12]。")])
        self.assertNotIn("[K12]", new_answer)
        self.assertIn("无效引用标记", note)
        self.assertIn("吃水加富裕深度", new_answer)


if __name__ == "__main__":
    unittest.main()
