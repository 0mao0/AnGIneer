"""agent 事件收集器（阶段 6）：emit 回调 + run 级投影的统一收口。

policy_query / evals 共用：替代裸 list.append 与手工 run_end 提取。
"""
from typing import Any, Dict, List

from angineer_core.agent_events import AgentEvent


class TraceCollector:
    """收集一次 run 的全部 AgentEvent，并提供稳定投影。"""

    def __init__(self) -> None:
        self.events: List[AgentEvent] = []

    def emit(self, event: AgentEvent) -> None:
        """直接作为 run_agent_loop 的 emit 回调使用。"""
        self.events.append(event)

    def run_end_payload(self) -> Dict[str, Any]:
        """最后一个 run_end 事件的 payload；无事件时返回 {}。"""
        run_end = next((e for e in reversed(self.events) if e.type == "run_end"), None)
        return dict(run_end.payload) if run_end else {}

    def agent_events_dump(self) -> List[Dict[str, Any]]:
        """全量事件的 JSON 序列化（retrieval_debug.agent_events 用）。"""
        return [event.model_dump(mode="json") for event in self.events]
