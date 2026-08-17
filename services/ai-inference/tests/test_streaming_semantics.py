"""流式重试语义：首 delta 前失败→换 provider；输出后失败→stream_failed / LLMStreamError。"""

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

from ai_inference.llm_client import LLMClient, LLMStreamError, RateLimitedError
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


def _client(models) -> LLMClient:
    return LLMClient(
        LLMClientConfig(models=models, default_model=models[0].name, retry=RetryConfig(max_retries=0))
    )


class TestStreamPreDeltaFallback(unittest.TestCase):
    def test_failure_before_first_delta_falls_back_to_next_provider(self):
        client = _client([_model("m1", 20), _model("m2", 10)])
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error()],
            stream_chunks=[helpers.make_chunk("m2 输出", "stop")],
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            events = list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        self.assertEqual([e["type"] for e in events], ["delta", "done"])
        self.assertEqual(events[0]["text"], "m2 输出")
        self.assertEqual(events[-1]["used_config"], "m2")


class TestStreamMidStreamFailure(unittest.TestCase):
    def test_failure_after_first_delta_emits_stream_failed_and_stops(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(
            stream_chunks=[
                helpers.make_chunk("你", None),
                helpers.rate_limit_error(),
                helpers.make_chunk("好", "stop"),
            ]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            events = list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        self.assertEqual([e["type"] for e in events], ["delta", "stream_failed"])
        self.assertEqual(events[0]["text"], "你")
        self.assertEqual(events[1]["text"], "你")
        self.assertIn("error", events[1])
        self.assertEqual(events[1]["error"]["type"], "RateLimitError")

    def test_chat_stream_raises_stream_error_with_partial_text(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(
            stream_chunks=[
                helpers.make_chunk("你", None),
                helpers.connection_error(),
            ]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(LLMStreamError) as ctx:
                list(client.chat_stream([{"role": "user", "content": "hi"}]))
        self.assertEqual(ctx.exception.partial_text, "你")

    def test_stream_failed_records_circuit_breaker_failure(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(
            stream_chunks=[helpers.make_chunk("你", None), helpers.connection_error()]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        status = client.get_circuit_breaker_status()["m1"]
        self.assertEqual(status["failure_count"], 1)
        self.assertEqual(status["state"], "closed")


class TestStreamMetadata(unittest.TestCase):
    def test_done_event_includes_metadata(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(
            stream_chunks=[helpers.make_chunk("完成", "stop")]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            events = list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        done = events[-1]
        self.assertEqual(done["type"], "done")
        self.assertEqual(done["used_config"], "m1")
        self.assertEqual(done["attempts"], 1)
        self.assertGreaterEqual(done["latency_seconds"], 0.0)
        self.assertEqual(done["circuit_breaker_state"], "closed")


if __name__ == "__main__":
    unittest.main()

