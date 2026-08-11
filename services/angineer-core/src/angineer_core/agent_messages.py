"""Agent 消息模型与 LLM 边界翻译（P2.1，§6.1）。

agent 侧使用轻量 dataclass；仅在 LLM 调用边界经 `to_llm_messages` 翻译为
OpenAI 兼容格式（P7 第二道闸门）。`meta` 永不进入 LLM 上下文。
"""
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


REFUSAL_ANSWER_TEXT = (
    "没有检索到足够证据支持最终结论。"
    "当前仅能确认已有片段与问题相关，但不足以安全地给出完整答案，请继续补充可核对的规范依据。"
)


@dataclass
class ToolCall:
    """循环侧生成的工具调用。id 形如 call_{turn}_{seq}。"""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class AgentMessage:
    """agent 侧统一消息。"""

    role: str  # "user" | "assistant" | "tool" | "system"
    content: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    tool_call_id: Optional[str] = None  # role="tool" 时回指
    name: Optional[str] = None  # role="tool" 时的工具名
    is_error: bool = False
    meta: Dict[str, Any] = field(default_factory=dict)  # citations/timings，不下发 LLM


def agent_message_to_dict(message: AgentMessage) -> Dict[str, Any]:
    """序列化为可 JSON 化的字典（用于事件/run_end，不含 meta）。"""
    data: Dict[str, Any] = {"role": message.role, "content": message.content}
    if message.tool_calls:
        data["tool_calls"] = [
            {"id": call.id, "name": call.name, "arguments": call.arguments}
            for call in message.tool_calls
        ]
    if message.tool_call_id:
        data["tool_call_id"] = message.tool_call_id
    if message.name:
        data["name"] = message.name
    if message.is_error:
        data["is_error"] = True
    return data


def to_llm_messages(
    messages: List[AgentMessage],
    tool_style: str = "text",
) -> List[Dict[str, Any]]:
    """翻译为 OpenAI 兼容消息。

    tool_style:
      - "text"：工具结果包装为 role="user"（文本协议，由 codec 决定）；
      - "native"：工具结果保留 role="tool"，assistant 消息携带 tool_calls。
    """
    llm_messages: List[Dict[str, Any]] = []
    for message in messages:
        role = message.role
        if role == "user":
            llm_messages.append({"role": "user", "content": message.content})
        elif role == "system":
            llm_messages.append({"role": "system", "content": message.content})
        elif role == "assistant":
            entry: Dict[str, Any] = {"role": "assistant", "content": message.content}
            if tool_style == "native" and message.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.name,
                            "arguments": json.dumps(call.arguments, ensure_ascii=False),
                        },
                    }
                    for call in message.tool_calls
                ]
            llm_messages.append(entry)
        elif role == "tool":
            if tool_style == "native":
                llm_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": message.tool_call_id or "",
                        "content": message.content,
                    }
                )
            else:
                label = f"[工具 {message.name or 'unknown'} 返回"
                if message.is_error:
                    label += "（错误）"
                label += "]"
                llm_messages.append({"role": "user", "content": f"{label}\n{message.content}"})
        else:
            # 未知角色兜底为 user，避免协议级崩溃
            llm_messages.append({"role": "user", "content": message.content})
    return llm_messages
