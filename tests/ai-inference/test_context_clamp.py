"""context-length 400 钳制重试单测（plan-evidence-admission 变更 C）。

覆盖：_context_clamp_tokens 解析（vLLM 两种报错形态/非 400/解析不出）；
_call_with_retry 钳制一次重试成功、钳制后仍 400 走原报错、非 400 不钳制。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))

from openai import APIError  # noqa: E402

from ai_inference.llm_client import LLMClient, _context_clamp_tokens  # noqa: E402


def _api_error(message: str, status: int) -> APIError:
    error = APIError(message, request=None, body=None)
    error.status_code = status
    return error


class ContextClampParseTests(unittest.TestCase):
    VLLM_CLASSIC = (
        "Error code: 400 - {'object': 'error', 'message': \"This model's maximum context length is 65536 tokens. "
        "However, you requested 4096 output tokens and your prompt contains 122882 characters, "
        "for a total of 61441 input tokens + 4096 output tokens. Please reduce the length of the "
        "input prompt or the number of requested output tokens. (parameter=input_tokens, value=61441)\"}"
    )

    def test_parses_vllm_message(self):
        self.assertEqual(_context_clamp_tokens(_api_error(self.VLLM_CLASSIC, 400)), 65536 - 61441 - 512)

    def test_non_400_not_clamped(self):
        self.assertIsNone(_context_clamp_tokens(_api_error(self.VLLM_CLASSIC, 500)))
        self.assertIsNone(_context_clamp_tokens(_api_error(self.VLLM_CLASSIC, 429)))

    def test_non_context_400_not_clamped(self):
        self.assertIsNone(_context_clamp_tokens(_api_error("Error code: 400 - bad request body", 400)))

    def test_unparseable_context_400_returns_none(self):
        msg = "maximum context length exceeded, sorry"  # 无 limit/input 数字
        self.assertIsNone(_context_clamp_tokens(_api_error(msg, 400)))

    def test_clamp_floor_too_small_returns_none(self):
        msg = "maximum context length is 65536 tokens; 65200 input tokens"
        self.assertIsNone(_context_clamp_tokens(_api_error(msg, 400)))  # 65536-65200-512=−176 <64


class ContextClampRetryTests(unittest.TestCase):
    """_call_with_retry：400→钳制一次；仍败走原报错；非 400 不触发钳制。"""

    _MSG = ContextClampParseTests.VLLM_CLASSIC

    def _fake_self(self, call_openai_side_effect):
        retry = SimpleNamespace(max_retries=2, initial_delay=0.0, exponential_base=2.0, max_delay=0.0)
        fake = SimpleNamespace(
            _config=SimpleNamespace(retry=retry),
            _call_openai=mock.Mock(side_effect=call_openai_side_effect),
        )
        return fake

    def test_clamped_retry_once_succeeds(self):
        fake = self._fake_self([
            _api_error(self._MSG, 400),
            SimpleNamespace(attempts=0, finish_reason="stop", text="ok"),
        ])
        result = LLMClient._call_with_retry(
            fake, SimpleNamespace(), [{"role": "user", "content": "q"}], 0.0, SimpleNamespace(), max_tokens=4096,
        )
        self.assertEqual(result.text, "ok")
        self.assertEqual(fake._call_openai.call_count, 2)
        second_max_tokens = fake._call_openai.call_args_list[1].args[4]
        self.assertEqual(second_max_tokens, 65536 - 61441 - 512)  # 钳制值只出现在重试那一次

    def test_clamp_attempted_once_then_original_error(self):
        fake = self._fake_self([
            _api_error(self._MSG, 400),
            _api_error(self._MSG, 400),
        ])
        with self.assertRaises(APIError):
            LLMClient._call_with_retry(
                fake, SimpleNamespace(), [{"role": "user", "content": "q"}], 0.0, SimpleNamespace(), max_tokens=4096,
            )
        self.assertEqual(fake._call_openai.call_count, 2)  # 钳制只有一次机会，不再反复试

    def test_non_context_400_no_clamp(self):
        fake = self._fake_self([_api_error("Error code: 400 - invalid schema", 400)])
        with self.assertRaises(APIError):
            LLMClient._call_with_retry(
                fake, SimpleNamespace(), [{"role": "user", "content": "q"}], 0.0, SimpleNamespace(), max_tokens=4096,
            )
        self.assertEqual(fake._call_openai.call_count, 1)
        self.assertEqual(fake._call_openai.call_args.args[4], 4096)  # 未动 max_tokens


if __name__ == "__main__":
    unittest.main()
