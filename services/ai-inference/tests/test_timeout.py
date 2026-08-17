"""超时配置完整生效：connect/read/write/pool/total 全部传入 OpenAI 客户端。"""

import asyncio
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

import httpx

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
    TimeoutConfig,
    load_llm_config_from_env,
)


def _model() -> LLMModelConfig:
    return LLMModelConfig(
        name="m1",
        model="model-m1",
        api_key="k",
        base_url="https://example.com",
        priority=10,
    )


def _client() -> LLMClient:
    return LLMClient(
        LLMClientConfig(
            models=[_model()],
            default_model="m1",
            retry=RetryConfig(max_retries=0),
            timeout=TimeoutConfig(connect=7.0, read=33.0, write=25.0, pool=9.0, total=99.0),
        )
    )


def _assert_timeout(timeout: httpx.Timeout):
    assert isinstance(timeout, httpx.Timeout)
    assert timeout.connect == 7.0
    assert timeout.read == 33.0
    assert timeout.write == 25.0
    assert timeout.pool == 9.0
    assert timeout == httpx.Timeout(99.0, connect=7.0, read=33.0, write=25.0, pool=9.0)


class TestTimeoutSync(unittest.TestCase):
    def test_sync_passes_full_timeout(self):
        client = _client()
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            client.chat_result([{"role": "user", "content": "hi"}])
        _assert_timeout(factory.kwargs[0]["timeout"])

    def test_stream_passes_full_timeout(self):
        client = _client()
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            list(client.chat_stream_events([{"role": "user", "content": "hi"}]))
        _assert_timeout(factory.kwargs[0]["timeout"])


class TestTimeoutAsync(unittest.TestCase):
    def test_async_passes_full_timeout(self):
        client = _client()
        completions = helpers.FakeAsyncCompletions()
        factory = helpers.make_async_factory(completions)
        with mock.patch("ai_inference.llm_client.AsyncOpenAI", factory):
            asyncio.run(client.achat_result([{"role": "user", "content": "hi"}]))
        _assert_timeout(factory.kwargs[0]["timeout"])


class TestTimeoutEnv(unittest.TestCase):
    def test_env_timeout_fields(self):
        env = {
            "ANGINEER_TIMEOUT_CONNECT": "7",
            "ANGINEER_TIMEOUT_READ": "33",
            "ANGINEER_TIMEOUT_WRITE": "25",
            "ANGINEER_TIMEOUT_POOL": "9",
            "ANGINEER_TIMEOUT_TOTAL": "99",
            "LLM_CONFIGS": "[]",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            config = load_llm_config_from_env()
        self.assertEqual(config.timeout.connect, 7.0)
        self.assertEqual(config.timeout.read, 33.0)
        self.assertEqual(config.timeout.write, 25.0)
        self.assertEqual(config.timeout.pool, 9.0)
        self.assertEqual(config.timeout.total, 99.0)


if __name__ == "__main__":
    unittest.main()
