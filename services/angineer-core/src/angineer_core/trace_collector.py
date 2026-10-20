"""agent 事件收集器（阶段 6）：emit 回调 + run 级投影的统一收口。

policy_query / evals 共用：替代裸 list.append 与手工 run_end 提取。
trace 直接消费事件流，不再另写一套派生字段（四步链已退役）。
"""
from typing import Any, Dict, List

from angineer_core.agent_events import AgentEvent

# trace 事件 schema 版本：事件字段增删时 +1；新工具/新路由不升版本。
TRACE_VERSION = 1

# 流式增量只服务聊天 SSE，进评测库纯占体积（单题 421 事件里 406 条是 delta）。
_TRACE_SKIP_EVENT_TYPES = ("message_delta",)


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
        """可入库的事件序列：过滤流式增量 + run_end 的整段消息副本。

        run_end.payload.messages 是整轮对话（含工具全文），与 answer/retrieved_items
        重复；UI 只读 reason/turns/final_outcome/path_trace，入库裁掉。
        """
        dumped: List[Dict[str, Any]] = []
        for event in self.events:
            if event.type in _TRACE_SKIP_EVENT_TYPES:
                continue
            item = event.model_dump(mode="json")
            if item.get("type") == "run_end":
                payload = dict(item.get("payload") or {})
                payload.pop("messages", None)
                payload.pop("answer_pre_strip", None)
                item["payload"] = payload
            dumped.append(item)
        # 多轮 prompt 只保留最后一轮全文：前面的轮次 messages 与后续 prompt 的历史部分重复，
        # 13 轮 L3 若全存可达数 MB。前面轮次保留 message_count/prompt_chars，UI 标注已省略。
        prompt_indices = [i for i, item in enumerate(dumped) if item.get("type") == "llm_request"]
        for index in prompt_indices[:-1]:
            payload = dict(dumped[index].get("payload") or {})
            payload.pop("messages", None)
            payload["messages_omitted"] = True
            dumped[index]["payload"] = payload
        return dumped

    def trace_payload(self, *, duration_ms: int = 0, agent_loop_ms: int = 0) -> Dict[str, Any]:
        """评测 run 的 trace 投影：{version, events, summary}。

        summary 在写库时算好，前端不必解析事件数组。
        duration_ms 是从请求开始的总时长（含意图分类）；agent_loop_ms 是循环段。
        """
        run_end = self.run_end_payload()
        events = self.agent_events_dump()
        tool_calls = sum(1 for event in events if event.get("type") == "tool_end")
        summary = {
            "turns": int(run_end.get("turns") or 0),
            "tool_calls": tool_calls,
            "duration_ms": int(duration_ms or 0),
            "agent_loop_ms": int(agent_loop_ms or 0),
            "reason": str(run_end.get("reason") or ""),
            "final_outcome": run_end.get("final_outcome"),
            "path_trace": list(run_end.get("path_trace") or []),
        }
        return {
            "version": TRACE_VERSION,
            "events": events,
            "summary": summary,
        }
