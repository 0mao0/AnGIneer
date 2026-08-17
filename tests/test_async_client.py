"""异步 API：achat / achat_result / achat_stream / achat_stream_events 与并发。"""

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

import helpers

from ai_inference.llm_client import LLMClient
from ai_inference.llm_config import (
    LLMClientConfig,
    LLMModelConfig,
    RetryConfig,
)


def _model() -> LLMModelConfig:
    return LLMModelConfig(
        name="m1",
        model="model-m1",
        api_key="k",
        base_url="https://example.com",
        priority=10,
    )


def _client(retry_max: int = 0) -> LLMClient:
    return LLMClient(
        LLMClientConfig(
            models=[_model()],
            default_model="m1",
            retry=RetryConfig(max_retries=retry_max),
        )
    )


class TestAsyncResult(unittest.TestCase):
    def test_achat_result_returns_text_and_metadata(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions()
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):
            result = asyncio.run(client.achat_result([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.text, "ok")
        self.assertEqual(result.used_config, "m1")

    def test_achat_returns_plain_text(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions()
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):
            text = asyncio.run(client.achat([{"role": "user", "content": "hi"}]))
        self.assertEqual(text, "ok")


class TestAsyncStream(unittest.TestCase):
    def test_achat_stream_events_yields_deltas_and_done(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions(
            stream_chunks=[
                helpers.make_chunk("你", None),
                helpers.make_chunk("好", "stop"),
            ]
        )
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):

            async def run():
                return [e async for e in client.achat_stream_events([{"role": "user", "content": "hi"}])]

            events = asyncio.run(run())
        self.assertEqual([e["type"] for e in events], ["delta", "delta", "done"])
        self.assertEqual(events[0]["text"], "你")
        self.assertEqual(events[-1]["finish_reason"], "stop")
        self.assertIn("used_config", events[-1])

    def test_achat_stream_yields_text_only(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions(
            stream_chunks=[helpers.make_chunk("你", None), helpers.make_chunk("好", "stop")]
        )
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):

            async def run():
                return [t async for t in client.achat_stream([{"role": "user", "content": "hi"}])]

            texts = asyncio.run(run())
        self.assertEqual(texts, ["你", "好"])


class TestAsyncRetry(unittest.TestCase):
    def test_async_retries_then_succeeds(self):
        client = _client(retry_max=1)
        completions = helpers.FakeAsyncCompletions(
            errors=[helpers.rate_limit_error()],
            results=[helpers.make_completion("ok after retry")],
        )
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):
            result = asyncio.run(client.achat_result([{"role": "user", "content": "hi"}]))
        self.assertEqual(result.text, "ok after retry")
        self.assertEqual(result.attempts, 2)


class TestAsyncConcurrency(unittest.TestCase):
    def test_concurrent_achat_calls_are_safe(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions()
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):

            async def run():
                results = await asyncio.gather(
                    *[client.achat_result([{"role": "user", "content": f"q{i}"}]) for i in range(10)]
                )
                return results

            results = asyncio.run(run())
        self.assertEqual(len(results), 10)
        self.assertTrue(all(r.text == "ok" for r in results))
        self.assertEqual(len(completions.calls), 10)


if __name__ == "__main__":
    unittest.main()

