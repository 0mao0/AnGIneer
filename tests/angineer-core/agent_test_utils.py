"""P2 测试共用工具：mock LLM 与事件构造。"""
import json
from typing import Any, Callable, Dict, Generator, List


class MockLLM:
    """按脚本返回 chat_stream_events 的假 LLM，记录每次调用。"""

    def __init__(self, handler: Callable[[List[Dict[str, Any]], Dict[str, Any]], Generator]):
        self.handler = handler
        self.calls: List[Dict[str, Any]] = []

    def chat_stream_events(self, messages: List[Dict[str, Any]], **kwargs: Any):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        yield from self.handler(messages, kwargs)


def text_events(text: str = "", finish_reason: str = "stop", usage: Dict[str, Any] | None = None):
    """生成 delta + done 事件序列。"""
    if text:
        yield {"type": "delta", "text": text}
    yield {"type": "done", "finish_reason": finish_reason, "usage": usage}


def tool_block(calls: List[Dict[str, Any]]) -> str:
    """构造文本协议工具调用块。"""
    return f"```tool_calls\n{json.dumps(calls, ensure_ascii=False)}\n```"


def collect_events(events: List[Any]) -> List[str]:
    return [e.type for e in events]
