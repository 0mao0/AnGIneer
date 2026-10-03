"""P4.1 build_complex_config 装配单元测试。"""
import os
import sys
import unittest
from unittest.mock import Mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_configs import (  # noqa: E402
    COMPLEX_AGENT_SYSTEM_PROMPT,
    build_complex_config,
)
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.tool_codec import TextToolCallCodec  # noqa: E402


class ComplexConfigTests(unittest.TestCase):
    def test_build_complex_config_assembles_full_toolset(self):
        config = build_complex_config(
            llm=Mock(),
            doc_nodes=[],
            library_id="default",
            doc_ids=[],
        )
        self.assertEqual(
            [tool.name for tool in config.tools],
            [
                "knowledge_search",
                "table_search",
                "entity_search",
                "sop_execute",
                "calculator",
                "conditional",
            ],
        )
        self.assertEqual(config.max_turns, 8)
        self.assertIsInstance(config.codec, TextToolCallCodec)
        self.assertIsNotNone(config.transform_context)
        self.assertIsNotNone(config.should_stop_after_turn)

    def test_sop_execute_tool_has_execution_contract(self):
        config = build_complex_config(llm=Mock())
        sop_tool = config.tools[3]
        self.assertEqual(sop_tool.name, "sop_execute")
        self.assertFalse(sop_tool.read_only)
        self.assertEqual(sop_tool.execution_mode, "sequential")
        self.assertEqual(sop_tool.timeout_s, 300)

    def test_complex_system_prompt_mentions_sop_and_tools(self):
        self.assertIn("sop_execute", COMPLEX_AGENT_SYSTEM_PROMPT)
        self.assertIn("calculator", COMPLEX_AGENT_SYSTEM_PROMPT)

    def test_custom_tools_override(self):
        tool = Mock(name="custom_tool")
        config = build_complex_config(llm=Mock(), tools=[tool])
        self.assertEqual(config.tools, [tool])
        self.assertEqual(config.max_turns, 8)

    def test_build_complex_config_installs_final_answer_guard(self):
        """2026-10-04 补装：L3/L4 此前无 guard，occamy 实测正文把表格检索的 T 前缀
        写成 [K3] 等假标记，既不被剥除、前端也渲染不出角标（裸文本给用户）。"""
        config = build_complex_config(llm=Mock())
        self.assertIsNotNone(config.final_answer_guard)

    def test_complex_guard_strips_wrong_prefix_markers(self):
        """复现实锤场景：检索结果只分配了 T1–T15，模型正文却引 [K1]/[T3]/[K99]。
        证据充足（items 有 text）→ 不触发 no_evidence；无效 K 标记被剥除。"""
        config = build_complex_config(llm=Mock())
        tool = AgentMessage(
            role="tool",
            content='{"items": [{"item_id":"a","text":"表 4.3.7 稳定系数","metadata":{"cite":"T3"}}]}',
        )
        final = AgentMessage(
            role="assistant",
            content="稳定系数按表 4.3.7 取 14.0 [T3]，容许失稳率见 [K1]，其余 [K99]。",
        )
        result = config.final_answer_guard([tool, final])
        self.assertIsNotNone(result)
        new_answer, note, code = result
        self.assertEqual(code, "markers_cleaned")
        self.assertIn("[T3]", new_answer)  # 有效标记保留
        self.assertNotIn("[K1]", new_answer)
        self.assertNotIn("[K99]", new_answer)
        self.assertIn("无效引用标记", note)

    def test_complex_guard_enforces_evidence(self):
        """与 L2 同口径：复杂档无证据时拒答（no_evidence）。"""
        config = build_complex_config(llm=Mock())
        tool = AgentMessage(role="tool", content='{"items": []}')
        final = AgentMessage(role="assistant", content="该护面块体重 250kg。")
        result = config.final_answer_guard([tool, final])
        self.assertIsNotNone(result)
        self.assertEqual(result[2], "no_evidence")


if __name__ == "__main__":
    unittest.main()
