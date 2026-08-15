"""
单元测试：LLMClient 结果结构（ChatResult）与流式事件。

对应 P0.1：chat_result / chat_stream_events / configs 脱敏 / tools 透传 /
contracts.LLMProvider 协议同步。
"""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/ai-inference/src")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/angineer-core/src")))

from ai_inference.llm_client import LLMClient, ChatResult, LLMTruncatedError, chat_result_guarded
from ai_inference.llm_config import (
    LLMClientConfig,
    LLMModelConfig,
    TimeoutConfig,
    RetryConfig,
    CircuitBreakerConfig,
)


def _make_client() -> LLMClient:
    """构造不依赖 .env 的测试客户端。"""
    config = LLMClientConfig(
        models=[
            LLMModelConfig(
                name="test",
                api_key="sk-test-secret",
                base_url="https://example.com/v1",
                model="test-model",
                enabled=True,
                priority=1,
            )
        ],
        default_model="test",
        max_tokens=2048,
        timeout=TimeoutConfig(total=5.0),
        retry=RetryConfig(max_retries=0),
        circuit_breaker=CircuitBreakerConfig(failure_threshold=5),
    )
    return LLMClient(config=config)


class TestChatResult(unittest.TestCase):
    """测试 ChatResult 数据模型。"""

    def test_chat_result_fields(self):
        result = ChatResult(text="你好", finish_reason="stop", usage={"total_tokens": 10})
        self.assertEqual(result.text, "你好")
        self.assertEqual(result.finish_reason, "stop")
        self.assertEqual(result.usage, {"total_tokens": 10})
        self.assertIsNone(result.tool_calls)


class TestChatResultMethod(unittest.TestCase):
    """测试 LLMClient.chat_result 返回完整结果。"""

    def test_chat_result_returns_full_result(self):
        client = _make_client()
        expected = ChatResult(text="你好", finish_reason="stop", usage={"total_tokens": 10})
        with mock.patch.object(client, "_call_with_retry", return_value=expected) as call:
            result = client.chat_result(
                [{"role": "user", "content": "hi"}],
                config_name="test",
            )
        self.assertIs(result, expected)
        call.assert_called_once()

    def test_chat_returns_text_only(self):
        client = _make_client()
        with mock.patch.object(
            client,
            "_call_with_retry",
            return_value=ChatResult(text="回答", finish_reason="stop"),
        ):
            self.assertEqual(
                client.chat([{"role": "user", "content": "hi"}], config_name="test"),
                "回答",
            )

    def test_chat_handles_none_content(self):
        """B7：chat 返回 None content 时不得抛错，应退化为空字符串。"""
        client = _make_client()
        with mock.patch.object(
            client,
            "_call_with_retry",
            return_value=ChatResult(text="", finish_reason=None),
        ):
            self.assertEqual(
                client.chat([{"role": "user", "content": "hi"}], config_name="test"),
                "",
            )


class TestChatStreamEvents(unittest.TestCase):
    """测试 chat_stream_events 事件流与 chat_stream 兼容。"""

    def test_chat_stream_events_yields_delta_and_done(self):
        client = _make_client()
        events = [
            {"type": "delta", "text": "你"},
            {"type": "done", "finish_reason": "stop", "usage": {"total_tokens": 5}},
        ]
        with mock.patch.object(client, "_call_openai_stream_events", return_value=iter(events)):
            got = list(
                client.chat_stream_events(
                    [{"role": "user", "content": "hi"}],
                    config_name="test",
                )
            )
        self.assertEqual(got, events)

    def test_chat_stream_keeps_text_only(self):
        """兼容：chat_stream 仍只产出纯文本 delta。"""
        client = _make_client()
        events = [
            {"type": "delta", "text": "你"},
            {"type": "delta", "text": "好"},
            {"type": "done", "finish_reason": "stop", "usage": {"total_tokens": 5}},
        ]
        with mock.patch.object(client, "_call_openai_stream_events", return_value=iter(events)):
            got = list(
                client.chat_stream(
                    [{"role": "user", "content": "hi"}],
                    config_name="test",
                )
            )
        self.assertEqual(got, ["你", "好"])

    def test_stream_request_includes_max_tokens_and_usage_option(self):
        """Q2：流式请求必须可传 max_tokens，并请求 usage（stream_options）。"""
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content="hi"), finish_reason="stop")],
                    usage=SimpleNamespace(prompt_tokens=1, completion_tokens=2),
                )
                return [chunk]

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = FakeChat()

        client = _make_client()
        with mock.patch("ai_inference.llm_client.OpenAI", FakeOpenAI):
            events = list(
                client._call_openai_stream_events(
                    client._get_model_configs("test")[0],
                    [{"role": "user", "content": "hi"}],
                    0.1,
                    client._config.timeout,
                    max_tokens=512,
                )
            )

        self.assertEqual(captured["max_tokens"], 512)
        self.assertEqual(captured["stream_options"], {"include_usage": True})
        self.assertEqual(events[0], {"type": "delta", "text": "hi"})
        self.assertEqual(events[1]["type"], "done")
        self.assertEqual(events[1]["finish_reason"], "stop")
        self.assertEqual(events[1]["usage"], {"prompt_tokens": 1, "completion_tokens": 2})

    def test_stream_done_without_usage_when_unsupported(self):
        """端点不支持 include_usage 时 done.usage 为 None，不抛错。"""
        class FakeCompletions:
            def create(self, **kwargs):
                chunk = SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=None), finish_reason="length")],
                    usage=None,
                )
                return [chunk]

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = FakeChat()

        client = _make_client()
        with mock.patch("ai_inference.llm_client.OpenAI", FakeOpenAI):
            events = list(
                client._call_openai_stream_events(
                    client._get_model_configs("test")[0],
                    [{"role": "user", "content": "hi"}],
                    0.1,
                    client._config.timeout,
                )
            )

        self.assertEqual(events[0]["type"], "done")
        self.assertEqual(events[0]["finish_reason"], "length")
        self.assertIsNone(events[0]["usage"])


class TestConfigsMasking(unittest.TestCase):
    """B6：configs 属性不得暴露明文 api_key。"""

    def test_configs_masks_api_key(self):
        client = _make_client()
        configs = client.configs
        self.assertEqual(len(configs), 1)
        self.assertEqual(configs[0]["api_key"], "***")
        self.assertNotIn("sk-test-secret", configs[0]["api_key"])


class TestToolsPassthrough(unittest.TestCase):
    """P0.1 任务 7：tools 参数透传到 OpenAI 请求。"""

    def test_chat_result_passes_tools_to_request(self):
        captured = {}

        class FakeCompletions:
            def create(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(
                                content=None,
                                tool_calls=[
                                    SimpleNamespace(
                                        id="call_1",
                                        function=SimpleNamespace(name="search", arguments='{"q":"x"}'),
                                    )
                                ],
                            )
                        )
                    ],
                    usage=None,
                )

        class FakeChat:
            completions = FakeCompletions()

        class FakeOpenAI:
            def __init__(self, *args, **kwargs):
                self.chat = FakeChat()

        client = _make_client()
        tools = [{"type": "function", "function": {"name": "search", "parameters": {}}}]
        with mock.patch("ai_inference.llm_client.OpenAI", FakeOpenAI):
            result = client.chat_result(
                [{"role": "user", "content": "hi"}],
                config_name="test",
                tools=tools,
            )

        self.assertEqual(captured["tools"], tools)
        self.assertEqual(result.text, "")
        self.assertEqual(result.tool_calls[0]["id"], "call_1")
        self.assertEqual(result.tool_calls[0]["function"]["name"], "search")


class TestChatResultGuarded(unittest.TestCase):
    """P0.2：截断守卫——finish_reason=length 时缩短输入重试一次，仍截断则显式失败。"""

    def test_returns_result_when_not_truncated(self):
        client = _make_client()
        expected = ChatResult(text="ok", finish_reason="stop")
        with mock.patch.object(client, "chat_result", return_value=expected) as call:
            result = chat_result_guarded(client, [{"role": "user", "content": "hi"}])
        self.assertIs(result, expected)
        call.assert_called_once()

    def test_retries_once_with_shortened_input_on_truncation(self):
        client = _make_client()
        calls = []

        def fake_chat_result(messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                return ChatResult(text="半截 JSON", finish_reason="length")
            return ChatResult(text="ok", finish_reason="stop")

        with mock.patch.object(client, "chat_result", side_effect=fake_chat_result):
            result = chat_result_guarded(
                client,
                [{"role": "user", "content": "A" * 100}],
            )

        self.assertEqual(result.text, "ok")
        self.assertEqual(len(calls), 2)
        self.assertLess(len(calls[1][0]["content"]), len(calls[0][0]["content"]))

    def test_raises_when_retry_still_truncated(self):
        client = _make_client()
        with mock.patch.object(
            client,
            "chat_result",
            return_value=ChatResult(text="还是截断", finish_reason="length"),
        ):
            with self.assertRaises(LLMTruncatedError) as ctx:
                chat_result_guarded(client, [{"role": "user", "content": "X" * 50}])
        self.assertEqual(ctx.exception.partial_text, "还是截断")

    def test_raises_when_input_cannot_shrink(self):
        client = _make_client()
        with mock.patch.object(
            client,
            "chat_result",
            return_value=ChatResult(text="截断", finish_reason="length"),
        ):
            with self.assertRaises(LLMTruncatedError):
                chat_result_guarded(client, [{"role": "user", "content": "x"}])


class TestLLMProviderProtocol(unittest.TestCase):
    """P0.1 任务 6：contracts.LLMProvider 同步新增方法。"""

    def test_protocol_exposes_new_methods(self):
        from angineer_core.contracts import LLMProvider

        self.assertTrue(hasattr(LLMProvider, "chat_result"))
        self.assertTrue(hasattr(LLMProvider, "chat_stream_events"))


if __name__ == "__main__":
    unittest.main()
