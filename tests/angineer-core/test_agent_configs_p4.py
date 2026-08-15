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
                "table_lookup",
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


if __name__ == "__main__":
    unittest.main()
