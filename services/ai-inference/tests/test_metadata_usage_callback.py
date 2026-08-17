"""ChatResult 元数据（latency/attempts/used_config/熔断状态）与 usage_callback 测试。"""

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
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


def _model(name: str = "m1", priority: int = 10) -> LLMModelConfig:
    return LLMModelConfig(
        name=name,
        model=f"model-{name}",
        api_key="k",
        base_url="https://example.com",
        enabled=True,
        priority=priority,
    )


def _client(models, usage_callback=None) -> LLMClient:
    return LLMClient(
        LLMClientConfig(
            models=models,
            default_model=models[0].name,
            retry=RetryConfig(max_retries=0),
        ),
        usage_callback=usage_callback,
    )


class TestChatResultMetadata(unittest.TestCase):
    def test_success_result_has_full_metadata(self):
        received = []
        client = _client([_model()], usage_callback=received.append)
        completions = helpers.FakeCompletions(
            results=[helpers.make_completion("ok", usage={"total_tokens": 5})]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "ok")
        self.assertIsNotNone(result.latency_seconds)
        self.assertGreaterEqual(result.latency_seconds, 0.0)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.used_config, "m1")
        self.assertEqual(result.used_model, "model-m1")
        self.assertEqual(result.circuit_breaker_state, "closed")
        self.assertEqual(result.usage, {"total_tokens": 5})
        self.assertEqual(len(received), 1)
        self.assertIs(received[0], result)

    def test_fallback_metadata_reports_used_config_and_attempts(self):
        client = _client([_model("m1", 20), _model("m2", 10)])
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error()],
            results=[helpers.make_completion("from m2")],
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.used_config, "m2")
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.text, "from m2")

    def test_usage_callback_exception_does_not_break_request(self):
        def bad_callback(result):
            raise RuntimeError("hook failed")

        client = _client([_model()], usage_callback=bad_callback)
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "ok")


class TestStreamMetadataAndCallback(unittest.TestCase):
    def test_done_event_carries_metadata_and_callback_gets_usage(self):
        received = []
        client = _client([_model()], usage_callback=received.append)
        completions = helpers.FakeCompletions(
            stream_chunks=[
                helpers.make_chunk("你", None),
                helpers.make_chunk("好", "stop", SimpleNamespace(prompt_tokens=1, completion_tokens=2)),
            ]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            events = list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        done = events[-1]
        self.assertEqual(done["type"], "done")
        for key in ("used_config", "used_model", "attempts", "latency_seconds", "circuit_breaker_state"):
            self.assertIn(key, done)
        self.assertEqual(done["used_config"], "m1")
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0].usage, {"prompt_tokens": 1, "completion_tokens": 2})
        self.assertEqual(received[0].text, "你好")
        self.assertEqual(received[0].used_config, "m1")


class TestAsyncMetadata(unittest.TestCase):
    def test_async_result_has_metadata(self):
        received = []
        client = _client([_model()], usage_callback=received.append)
        completions = helpers.FakeAsyncCompletions()
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):
            result = asyncio.run(client.achat_result([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.used_config, "m1")
        self.assertEqual(result.attempts, 1)
        self.assertEqual(len(received), 1)


if __name__ == "__main__":
    unittest.main()

