"""P2 tool_codec 与消息翻译单测。"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from angineer_core.agent_messages import AgentMessage, ToolCall, to_llm_messages  # noqa: E402
from angineer_core.agent_tools import AgentTool  # noqa: E402
from angineer_core.tool_codec import NativeToolCallCodec, TextToolCallCodec  # noqa: E402


def dummy_tool(name="search", description="检索工具"):
    return AgentTool(
        name=name,
        description=description,
        parameters_schema={
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        },
        handler=lambda **kw: {"ok": True},
    )


class TextToolCallCodecTests(unittest.TestCase):
    def test_augment_system_prompt_contains_tools_and_protocol(self):
        codec = TextToolCallCodec()
        prompt = codec.augment_system_prompt("基础提示", [dummy_tool()])
        self.assertIn("基础提示", prompt)
        self.assertIn("search", prompt)
        self.assertIn("检索工具", prompt)
        self.assertIn("tool_calls", prompt)

    def test_augment_system_prompt_empty_tools_disables_calls(self):
        codec = TextToolCallCodec()
        prompt = codec.augment_system_prompt("基础提示", [])
        self.assertIn("禁用", prompt)
        self.assertNotIn("tool_calls", prompt)

    def test_parse_assistant_single_tool_call(self):
        codec = TextToolCallCodec()
        text, calls = codec.parse_assistant(
            "先检索\n```tool_calls\n[{\"name\": \"search\", \"arguments\": {\"q\": \"x\"}}]\n```"
        )
        self.assertIn("先检索", text)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search")
        self.assertEqual(calls[0].arguments, {"q": "x"})
        self.assertTrue(calls[0].id.startswith("call_"))

    def test_parse_assistant_multiple_tool_calls(self):
        codec = TextToolCallCodec()
        _, calls = codec.parse_assistant(
            "```tool_calls\n["
            '{"name": "a", "arguments": {"x": 1}},'
            '{"name": "b", "arguments": {"y": 2}}'
            "]\n```"
        )
        self.assertEqual([c.name for c in calls], ["a", "b"])
        self.assertEqual(len({c.id for c in calls}), 2)

    def test_parse_assistant_failure_fails_open_to_text(self):
        codec = TextToolCallCodec()
        text, calls = codec.parse_assistant("```tool_calls\n[broken json\n```")
        self.assertEqual(calls, [])
        self.assertIn("broken json", text)

    def test_parse_assistant_salvages_missing_closing_brace(self):
        """模型偶发少打一个 }（如 q_030：arguments 闭合后直接 ]），应宽容修复并执行。"""
        valid_body = '[{"name": "search", "arguments": {"q": "x"}}]'
        malformed_body = valid_body[: valid_body.rindex("}")] + "]"
        with self.assertRaises(json.JSONDecodeError):
            json.loads(malformed_body)
        codec = TextToolCallCodec()
        text, calls = codec.parse_assistant(
            "先检索\n```tool_calls\n" + malformed_body + "\n```"
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search")
        self.assertEqual(calls[0].arguments, {"q": "x"})
        self.assertIn("先检索", text)

    def test_parse_plain_json_array_without_fence(self):
        codec = TextToolCallCodec()
        text, calls = codec.parse_assistant(
            '[{"name": "search", "arguments": {"q": "x"}}]'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search")
        self.assertEqual(calls[0].arguments, {"q": "x"})
        self.assertEqual(text.strip(), "")

    def test_parse_plain_json_array_mixed_with_text(self):
        codec = TextToolCallCodec()
        text, calls = codec.parse_assistant(
            '先思考\n[{"name": "search", "arguments": {"q": "x"}}]'
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].name, "search")
        self.assertIn("先思考", text)
        self.assertNotIn('"name"', text)

    def test_native_codec_is_reserved(self):
        codec = NativeToolCallCodec()
        self.assertEqual(codec.augment_system_prompt("base", [dummy_tool()]), "base")
        with self.assertRaises(NotImplementedError):
            codec.parse_assistant("任意文本")


class ToLlmMessagesTests(unittest.TestCase):
    def test_text_style_wraps_tool_result_as_user(self):
        messages = [
            AgentMessage(role="user", content="问题"),
            AgentMessage(role="assistant", content="```tool_calls\n[]\n```"),
            AgentMessage(
                role="tool",
                content='{"result": "r"}',
                tool_call_id="call_1_1",
                name="search",
                is_error=False,
                meta={"citation": "x"},
            ),
        ]
        llm_messages = to_llm_messages(messages, tool_style="text")
        self.assertEqual(llm_messages[0]["role"], "user")
        self.assertEqual(llm_messages[1]["role"], "assistant")
        self.assertEqual(llm_messages[2]["role"], "user")
        self.assertIn("search", llm_messages[2]["content"])
        self.assertIn("r", llm_messages[2]["content"])
        self.assertNotIn("citation", llm_messages[2])

    def test_native_style_keeps_tool_role_and_assistant_tool_calls(self):
        messages = [
            AgentMessage(
                role="assistant",
                content="",
                tool_calls=[ToolCall(id="call_1_1", name="search", arguments={"q": "x"})],
            ),
            AgentMessage(
                role="tool",
                content="ok",
                tool_call_id="call_1_1",
                name="search",
            ),
        ]
        llm_messages = to_llm_messages(messages, tool_style="native")
        self.assertEqual(llm_messages[0]["role"], "assistant")
        self.assertEqual(llm_messages[0]["tool_calls"][0]["function"]["name"], "search")
        self.assertEqual(llm_messages[1]["role"], "tool")
        self.assertEqual(llm_messages[1]["tool_call_id"], "call_1_1")


if __name__ == "__main__":
    unittest.main()
