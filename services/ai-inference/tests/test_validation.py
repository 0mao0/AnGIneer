"""输入校验：messages / tools 尽早暴露调用方错误。"""

import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import helpers

from ai_inference.llm_client import LLMClient
from ai_inference.llm_config import (
    LLMClientConfig,
    LLMModelConfig,
    RetryConfig,
)


def _client() -> LLMClient:
    model = LLMModelConfig(
        name="m1",
        model="model-m1",
        api_key="k",
        base_url="https://example.com",
        priority=10,
    )
    return LLMClient(
        LLMClientConfig(models=[model], default_model="m1", retry=RetryConfig(max_retries=0))
    )


class TestMessagesValidation(unittest.TestCase):
    def test_messages_must_be_list(self):
        client = _client()
        with self.assertRaises(ValueError):
            client.chat_result("not a list")

    def test_message_must_be_dict(self):
        client = _client()
        with self.assertRaises(ValueError):
            client.chat_result([("role", "user")])

    def test_message_requires_role(self):
        client = _client()
        with self.assertRaisesRegex(ValueError, r"messages\[0\]"):
            client.chat_result([{"content": "hi"}])

    def test_valid_messages_pass(self):
        client = _client()
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result(
                [
                    {"role": "system", "content": "sys"},
                    {"role": "user", "content": "hi"},
                ]
            )
        self.assertEqual(result.text, "ok")


class TestToolsValidation(unittest.TestCase):
    def test_tools_must_be_list(self):
        client = _client()
        with self.assertRaises(ValueError):
            client.chat_result([{"role": "user", "content": "hi"}], tools="not a list")

    def test_tool_requires_function_name(self):
        client = _client()
        tools = [{"type": "function", "function": {"parameters": {}}}]
        with self.assertRaisesRegex(ValueError, r"tools\[0\]"):
            client.chat_result([{"role": "user", "content": "hi"}], tools=tools)

    def test_valid_tools_pass(self):
        client = _client()
        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result(
                [{"role": "user", "content": "hi"}], tools=tools
            )
        self.assertEqual(result.text, "ok")


if __name__ == "__main__":
    unittest.main()

