"""线程安全：单例初始化与并发调用。"""

import os
import sys
import threading
import unittest
from pathlib import Path
from unittest import mock

TESTS_DIR = Path(__file__).resolve().parent
SRC = TESTS_DIR.parent / "src"
for p in (str(SRC), str(TESTS_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)

import helpers

from ai_inference.llm_client import LLMClient, get_llm_client, reset_llm_client
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


class TestSingletonThreadSafety(unittest.TestCase):
    def test_concurrent_get_llm_client_returns_single_instance(self):
        env = {
            "LLM_CONFIGS": (
                '[{"name":"m1","model":"model-m1","api_key":"k",'
                '"base_url":"https://example.com","priority":10}]'
            ),
            "ANGINEER_DEFAULT_MODEL": "m1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            reset_llm_client()
            try:
                results = []
                errors = []

                def worker():
                    try:
                        results.append(get_llm_client())
                    except Exception as exc:  # pragma: no cover
                        errors.append(exc)

                threads = [threading.Thread(target=worker) for _ in range(8)]
                for t in threads:
                    t.start()
                for t in threads:
                    t.join()
                self.assertEqual(errors, [])
                self.assertEqual(len(set(id(r) for r in results)), 1)
            finally:
                reset_llm_client()


class TestConcurrentCalls(unittest.TestCase):
    def test_concurrent_chat_result_calls_on_shared_client(self):
        client = LLMClient(
            LLMClientConfig(models=[_model()], default_model="m1", retry=RetryConfig(max_retries=0))
        )
        completions = helpers.FakeCompletions()
        factory = helpers.make_sync_factory(completions)
        results = []
        errors = []

        def worker():
            try:
                for _ in range(5):
                    results.append(client.chat_result([{"role": "user", "content": "hi"}]))
            except Exception as exc:  # pragma: no cover
                errors.append(exc)

        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            threads = [threading.Thread(target=worker) for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

        self.assertEqual(errors, [])
        self.assertEqual(len(results), 40)
        self.assertTrue(all(r.text == "ok" for r in results))
        status = client.get_circuit_breaker_status()["m1"]
        self.assertEqual(status["total_calls"], 40)


if __name__ == "__main__":
    unittest.main()

