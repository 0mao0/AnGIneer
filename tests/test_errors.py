"""错误分类测试：层级、映射、AllProvidersFailedError。"""

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
    LLMClient,
    LLMError,
    LLMTruncatedError,
    ProviderAuthError,
    ProviderUnavailableError,
    RateLimitedError,
    AllProvidersFailedError,
)
from ai_inference.llm_config import (
    LLMClientConfig,
    LLMModelConfig,
    RetryConfig,
)
from ai_inference.llm_response_parser import ParseError


def _model(name: str = "m1") -> LLMModelConfig:
    return LLMModelConfig(
        name=name,
        model=f"model-{name}",
        api_key="k",
        base_url="https://example.com",
        enabled=True,
        priority=10,
    )


def _client(models, retry_max: int = 0) -> LLMClient:
    return LLMClient(
        LLMClientConfig(
            models=models,
            default_model=models[0].name,
            retry=RetryConfig(max_retries=retry_max),
        )
    )


class TestErrorHierarchy(unittest.TestCase):
    def test_typed_errors_subclass_llm_error(self):
        for cls in (
            ProviderUnavailableError,
            ProviderAuthError,
            RateLimitedError,
            LLMTruncatedError,
            AllProvidersFailedError,
        ):
            self.assertTrue(issubclass(cls, LLMError), cls)
            self.assertTrue(issubclass(cls, Exception), cls)

    def test_parse_error_subclasses_llm_error(self):
        self.assertTrue(issubclass(ParseError, LLMError))

    def test_llm_truncated_error_keeps_partial_text(self):
        err = LLMTruncatedError("截断", partial_text='{"a":')
        self.assertEqual(err.partial_text, '{"a":')

    def test_all_providers_failed_carries_last_error(self):
        cause = RateLimitedError("rate limited")
        err = AllProvidersFailedError("所有 provider 失败", last_error=cause)
        self.assertIs(err.last_error, cause)


class TestErrorMapping(unittest.TestCase):
    def test_rate_limit_mapped(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(errors=[helpers.rate_limit_error()])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(RateLimitedError):
                client.chat_result([{"role": "user", "content": "hi"}])

    def test_auth_error_mapped(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(errors=[helpers.auth_error()])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(ProviderAuthError):
                client.chat_result([{"role": "user", "content": "hi"}])

    def test_connection_error_mapped(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(errors=[helpers.connection_error()])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(ProviderUnavailableError):
                client.chat_result([{"role": "user", "content": "hi"}])

    def test_timeout_error_mapped(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(errors=[helpers.timeout_error()])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(ProviderUnavailableError):
                client.chat_result([{"role": "user", "content": "hi"}])

    def test_5xx_api_error_mapped_to_unavailable(self):
        client = _client([_model()])
        completions = helpers.FakeCompletions(errors=[helpers.api_error(status=503)])
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(ProviderUnavailableError):
                client.chat_result([{"role": "user", "content": "hi"}])


class TestAllProvidersFailed(unittest.TestCase):
    def test_all_providers_failed_wraps_last_error(self):
        client = _client([_model("m1"), _model("m2")])
        completions = helpers.FakeCompletions(
            errors=[helpers.rate_limit_error(), helpers.rate_limit_error()]
        )
        factory = helpers.make_sync_factory(completions)
        with mock.patch("ai_inference.llm_client.OpenAI", factory):
            with self.assertRaises(AllProvidersFailedError) as ctx:
                client.chat_result([{"role": "user", "content": "hi"}])
        self.assertIsInstance(ctx.exception.last_error, RateLimitedError)


if __name__ == "__main__":
    unittest.main()

