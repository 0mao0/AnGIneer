"""工具调用协议（P2.1，§7）。

默认 `TextToolCallCodec`：ReAct 式文本协议，兼容一切 OpenAI 兼容端点。
`NativeToolCallCodec` 预留：走原生 tools= 参数，默认不启用。
"""
import json
import logging
import re
from typing import Any, Dict, List, Optional, Protocol, Tuple

from angineer_core.agent_messages import ToolCall
from angineer_core.agent_tools import AgentTool

logger = logging.getLogger(__name__)


class ToolCallCodec(Protocol):
    def augment_system_prompt(self, base: str, tools: List[AgentTool]) -> str:
        ...

    def parse_assistant(self, text: str) -> Tuple[str, List[ToolCall]]:
        """返回 (纯文本部分, 工具调用列表)。空列表 = 模型没要工具 = 循环正常停。"""
        ...


class TextToolCallCodec:
    """文本工具调用协议：模型输出 ```tool_calls JSON 数组``` 块。"""

    def __init__(self, call_prefix: str = "call"):
        self._call_prefix = call_prefix
        self._seq = 0

    def augment_system_prompt(self, base: str, tools: List[AgentTool]) -> str:
        if not tools:
            return base + (
                "\n\n（注意：本轮工具调用已被禁用，请直接输出最终答案，"
                "不要输出任何工具调用代码块。）"
            )

        tools_json = json.dumps(
            [
                {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.parameters_schema,
                }
                for tool in tools
            ],
            ensure_ascii=False,
            indent=2,
        )
        protocol = (
            "\n\n## 工具使用协议\n"
            "你可以调用以下工具获取证据或执行计算：\n"
            f"{tools_json}\n\n"
            "规则：\n"
            "1. 需要调用工具时，只输出一个工具调用代码块，不要输出其他内容：\n"
            '```tool_calls\n[{"name": "工具名", "arguments": {"参数名": "参数值"}}]\n```\n'
            "2. 可以一次调用多个工具（数组内放多个对象）。\n"
            "3. 工具结果会以「工具返回」的形式提供给你。你可以继续调用工具，或给出最终答案。\n"
            "4. 当你掌握足够证据时，直接输出最终答案（不要包含 tool_calls 代码块）。\n"
            "5. 禁止编造工具返回中不存在的数字与结论。\n"
            "6. 调用工具前不要输出任何解释或引导语，直接输出工具调用代码块；工具调用块之外不要夹杂对话文字。\n"
            "7. 最终答案不要以提问方式收尾（如「您是否想知道…」），直接给出结论后结束。"
        )
        return base + protocol

    def parse_assistant(self, text: str) -> Tuple[str, List[ToolCall]]:
        """解析 tool_calls 块；无围栏时尝试 salvage 纯 JSON 数组，避免漏进正文。"""
        text = text or ""
        match = re.search(r"```tool_calls\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
        if match:
            calls = self._parse_calls_from_raw(match.group(1))
            if calls is not None:
                cleaned = re.sub(
                    r"```tool_calls\s*.*?```",
                    "",
                    text,
                    flags=re.DOTALL | re.IGNORECASE,
                ).strip()
                return cleaned, calls
            return text, []
        calls, span = self._salvage_plain_tool_calls(text)
        if calls:
            return text.replace(span, " ").strip(), calls
        return text, []

    def _parse_calls_from_raw(self, raw: str) -> Optional[List[ToolCall]]:
        """解析 JSON 字符串为工具调用列表；非 JSON 返回 None。"""
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return self._parse_calls_from_value(parsed)

    def _parse_calls_from_value(self, parsed: Any) -> Optional[List[ToolCall]]:
        if not isinstance(parsed, list):
            return None

        calls: List[ToolCall] = []
        for item in parsed:
            if not isinstance(item, dict) or not item.get("name"):
                continue
            self._seq += 1
            calls.append(
                ToolCall(
                    id=f"{self._call_prefix}_{self._seq}",
                    name=str(item["name"]),
                    arguments=item.get("arguments") if isinstance(item.get("arguments"), dict) else {},
                )
            )
        return calls

    def _salvage_plain_tool_calls(self, text: str) -> Tuple[Optional[List[ToolCall]], str]:
        """无围栏时扫描 JSON 数组，识别工具调用并返回其原文片段。"""
        decoder = json.JSONDecoder()
        for idx, ch in enumerate(text):
            if ch != "[":
                continue
            try:
                value, end = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue
            if not isinstance(value, list):
                continue
            calls = self._parse_calls_from_value(value)
            if calls:
                return calls, text[idx : idx + end]
        return None, ""


class NativeToolCallCodec:
    """原生工具调用（预留）。

    走 LLM 的 tools= 参数与 message.tool_calls。默认不启用：
    仅当某端点验证支持后按 config_name 白名单启用（R3）。
    """

    def augment_system_prompt(self, base: str, tools: List[AgentTool]) -> str:
        return base

    def parse_assistant(self, text: str) -> Tuple[str, List[ToolCall]]:
        raise NotImplementedError(
            "NativeToolCallCodec 预留：需端点验证 tools= 支持后按 config_name 白名单启用"
        )
