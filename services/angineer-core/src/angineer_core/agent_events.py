"""Agent 事件模型（P2.1，§6.2）。

镜像 π 的十种事件、四个层级；用 pydantic 以便 SSE 直接 model_dump_json()。
事件类型即协议：run_start/run_end、turn_start/turn_end、
message_start/message_delta/message_end、tool_start/tool_end、error，
另加 note（边界/过程说明）与 answer（边界规则替换最终回答）。
"""
import time
from typing import Any, Dict

from pydantic import BaseModel, Field


class AgentEvent(BaseModel):
    type: str
    run_id: str
    turn: int = 0
    ts: float = Field(default_factory=time.time)
    payload: Dict[str, Any] = Field(default_factory=dict)
