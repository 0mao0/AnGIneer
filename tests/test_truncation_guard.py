"""截断守卫（包内回归）：缩短重试、仍截断抛 LLMTruncatedError、异步守卫。"""

import asyncio
import sys
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

from ai_inference.llm_client import (
    ChatResult,
    LLMTruncatedError,
    LLMClient,
    achat_result_guarded,
    chat_result_guarded,
)
from ai_inference.llm_config import LLMClientConfig, LLMModelConfig, RetryConfig


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


class TestChatResultGuarded(unittest.TestCase):
    def test_returns_result_when_not_truncated(self):
        client = _client()
        expected = ChatResult(text="ok", finish_reason="stop")
        with mock.patch.object(client, "chat_result", return_value=expected) as call:
            result = chat_result_guarded(client, [{"role": "user", "content": "hi"}])
        self.assertIs(result, expected)
        call.assert_called_once()

    def test_retries_once_with_shortened_input(self):
        client = _client()
        calls = []

        def fake(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return ChatResult(text="半截", finish_reason="length")
            return ChatResult(text="ok", finish_reason="stop")

        with mock.patch.object(client, "chat_result", side_effect=fake):
            result = chat_result_guarded(client, [{"role": "user", "content": "A" * 100}])
        self.assertEqual(result.text, "ok")
        self.assertEqual(len(calls), 2)
        self.assertLess(len(calls[1][0]["content"]), len(calls[0][0]["content"]))

    def test_raises_when_still_truncated(self):
        client = _client()
        with mock.patch.object(
            client,
            "chat_result",
            return_value=ChatResult(text="还是截断", finish_reason="length"),
        ):
            with self.assertRaises(LLMTruncatedError) as ctx:
                chat_result_guarded(client, [{"role": "user", "content": "X" * 50}])
        self.assertEqual(ctx.exception.partial_text, "还是截断")


class TestAsyncChatResultGuarded(unittest.TestCase):
    def test_async_guarded_success(self):
        client = _client()
        expected = ChatResult(text="ok", finish_reason="stop")
        with mock.patch.object(client, "achat_result", return_value=expected) as call:
            result = asyncio.run(
                achat_result_guarded(client, [{"role": "user", "content": "hi"}])
            )
        self.assertIs(result, expected)
        call.assert_called_once()

    def test_async_guarded_raises_on_truncation(self):
        client = _client()
        with mock.patch.object(
            client,
            "achat_result",
            return_value=ChatResult(text="截断", finish_reason="length"),
        ):
            with self.assertRaises(LLMTruncatedError):
                asyncio.run(
                    achat_result_guarded(client, [{"role": "user", "content": "X" * 50}])
                )


if __name__ == "__main__":
    unittest.main()

