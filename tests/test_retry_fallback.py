"""指数退避重试、多模型 fallback、AllProvidersFailedError。"""

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

from ai_inference.llm_client import (
    AllProvidersFailedError,
    CircuitState,
    LLMClient,
    ProviderAuthError,
    RateLimitedError,
)
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


def _client(models, retry_max: int = 0) -> LLMClient:
    return LLMClient(
        LLMClientConfig(
            models=models,
            default_model=models[0].name,
            retry=RetryConfig(max_retries=retry_max, initial_delay=0.5),
        )
    )


class TestRetryBackoff(unittest.TestCase):
    def test_retries_with_exponential_backoff_and_reports_attempts(self):
        client = _client([_model()], retry_max=2)
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error(), helpers.rate_limit_error()],
            results=[helpers.make_completion("third time ok")],
        )
        factory = helpers.make_sync_factory(completions)
        sleeps = []
        with mock.patch("ai_inference.llm_client.time.sleep", side_effect=lambda d: sleeps.append(d)):
            with mock.patch("ai_inference.llm_client.OpenAI", factory):
                result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "third time ok")
        self.assertEqual(result.attempts, 3)
        self.assertEqual(sleeps, [0.5, 1.0])

    def test_non_retryable_auth_error_does_not_retry(self):
        client = _client([_model()], retry_max=3)
        completions = helpers.FakeCompletions(errors=[helpers.auth_error()])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(ProviderAuthError):
                client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(len(completions.calls), 1)


class TestMultiModelFallback(unittest.TestCase):
    def test_first_provider_fails_then_second_succeeds(self):
        client = _client([_model("m1", 20), _model("m2", 10)])
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error()],
            results=[helpers.make_completion("from m2")],
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.text, "from m2")
        self.assertEqual(result.used_config, "m2")
        self.assertEqual(result.attempts, 2)

    def test_all_providers_fail_raises_all_providers_failed(self):
        client = _client([_model("m1", 20), _model("m2", 10)])
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error(), helpers.rate_limit_error()]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(AllProvidersFailedError) as ctx:
                client.chat_result([{"role": "user", "content": "hi"}])
        self.assertIsInstance(ctx.exception.last_error, RateLimitedError)

    def test_open_circuit_breaker_skips_provider(self):
        client = _client([_model("m1", 20), _model("m2", 10)])
        client._circuit_breakers["m1"].record_failure(ValueError("boom"))
        client._circuit_breakers["m1"].state = CircuitState.OPEN
        completions = helpers.FakeCompletions(
            results=[helpers.make_completion("only m2 available")]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            result = client.chat_result([{"role": "user", "content": "hi"}])
        self.assertEqual(result.used_config, "m2")


if __name__ == "__main__":
    unittest.main()
