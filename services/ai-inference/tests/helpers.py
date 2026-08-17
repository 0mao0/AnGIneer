"""共享测试工具：fake OpenAI 客户端、异常构造、httpx 超时断言。"""

import httpx
from types import SimpleNamespace

from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    InternalServerError,
    RateLimitError,
)


def make_request() -> httpx.Request:
    return httpx.Request("POST", "https://example.com/v1/chat/completions")


def make_response(status: int = 500) -> httpx.Response:
    return httpx.Response(status, request=make_request())


def rate_limit_error(message: str = "rate limited") -> RateLimitError:
    return RateLimitError(message, response=make_response(429), body=None)


def auth_error(message: str = "bad api key") -> AuthenticationError:
    return AuthenticationError(message, response=make_response(401), body=None)


def connection_error(message: str = "connection error") -> APIConnectionError:
    return APIConnectionError(message=message, request=make_request())


def timeout_error() -> APITimeoutError:
    return APITimeoutError(request=make_request())


def api_error(message: str = "internal error", status: int = 500):
    return InternalServerError(message, response=make_response(status), body=None)


def make_chunk(content=None, finish_reason=None, usage=None, tool_calls=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


def make_completion(content="ok", finish_reason="stop", usage=None, tool_calls=None):
    message = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=message, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], usage=usage)


class FakeCompletions:
    """同步 completions 假实现。

    - errors: 每次 create 弹出一个并抛出（含 stream 模式 create 阶段）；
    - results: 非流式按序返回；
    - stream_chunks: 流式迭代内容，列表项若是 Exception 则在该位置抛出（模拟中途失败）。
    """

    def __init__(self, results=None, errors=None, stream_chunks=None):
        self.results = list(results or [])
        self.errors = list(errors or [])
        self.stream_chunks = list(stream_chunks) if stream_chunks is not None else [
            make_chunk("hi", "stop", SimpleNamespace(prompt_tokens=1, completion_tokens=2))
        ]
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            if self.errors:
                raise self.errors.pop(0)
            return self._stream()
        if self.errors:
            raise self.errors.pop(0)
        if self.results:
            return self.results.pop(0)
        return make_completion()

    def _stream(self):
        for item in self.stream_chunks:
            if isinstance(item, Exception):
                raise item
            yield item


class FakeAsyncCompletions(FakeCompletions):
    """异步 completions 假实现，行为与 FakeCompletions 一致。"""

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        if kwargs.get("stream"):
            if self.errors:
                raise self.errors.pop(0)
            return self._astream()
        if self.errors:
            raise self.errors.pop(0)
        if self.results:
            return self.results.pop(0)
        return make_completion()

    async def _astream(self):
        for item in self.stream_chunks:
            if isinstance(item, Exception):
                raise item
            yield item


class SyncHarness:
    """记录 OpenAI 构造参数并返回带 FakeCompletions 的假客户端。"""

    def __init__(self, completions=None):
        self.completions = completions or FakeCompletions()
        self.kwargs = []

    def __call__(self, **kwargs):
        self.kwargs.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


class AsyncHarness:
    """记录 AsyncOpenAI 构造参数并返回带 FakeAsyncCompletions 的假客户端。"""

    def __init__(self, completions=None):
        self.completions = completions or FakeAsyncCompletions()
        self.kwargs = []

    def __call__(self, **kwargs):
        self.kwargs.append(kwargs)
        return SimpleNamespace(chat=SimpleNamespace(completions=self.completions))


def make_sync_factory(completions=None) -> SyncHarness:
    return SyncHarness(completions)


def make_async_factory(completions=None) -> AsyncHarness:
    return AsyncHarness(completions)
