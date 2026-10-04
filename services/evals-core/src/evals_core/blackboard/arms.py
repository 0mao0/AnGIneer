"""三臂 prompt 组装与分段度量（arms §1）。

- **臂 1 / 臂 2** 走**生产同一段代码**（``agent_configs.make_budget_transformer``），只切
  ``ANGINEER_POINTER_SKELETON`` 开关——这保证「臂 1 = 现状」不是另写一份仿真，而是同一实现；
- **臂 3** 是 M0 的离线替身（生产读路径到 M2 才有）：历史 tool 原文**整条移出 prompt**，
  改由离线图渲染的相关子图段承接；段位按 BB §2 段序——**语义层逐字史之后、本轮提问之前**；
- 臂 3 在 M0 里**不做语义层截断**（那是 BB §2.2 的另一条闸），只替换证据层，便于把两件事分开看。

度量口径：est = 字符数 ÷ 2（与 ``agent_configs._estimate_tokens`` 逐位一致）。
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from angineer_core.agent_configs import (
    POINTER_SKELETON_ENV,
    _is_injected_user_prompt,
    make_budget_transformer,
)
from angineer_core.agent_messages import AgentMessage

from .graph import OfflineGraph, build_graph, recall, render

ARM_A_MIN = "arm1"      # 现状 A-min（开关关）
ARM_POINTER = "arm2"    # 指针骨架（开关开）
ARM_GRAPH = "arm3"      # 会话图（历史 tool 原文不进 prompt + 子图段）

ARM_LABELS = {
    ARM_A_MIN: "臂 1 现状 A-min",
    ARM_POINTER: "臂 2 指针骨架",
    ARM_GRAPH: "臂 3 会话图",
}
ALL_ARMS = (ARM_A_MIN, ARM_POINTER, ARM_GRAPH)


def estimate(messages: Sequence[AgentMessage]) -> int:
    """est token = 字符数 ÷ 2（与 agent_configs._estimate_tokens 同口径）。"""
    return sum(len(m.content or "") for m in messages) // 2


@contextmanager
def pointer_switch(enabled: bool):
    """临时切 ``ANGINEER_POINTER_SKELETON``（臂 1/臂 2 唯一的差别就是它）。"""
    original = os.environ.get(POINTER_SKELETON_ENV)
    os.environ[POINTER_SKELETON_ENV] = "1" if enabled else "0"
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(POINTER_SKELETON_ENV, None)
        else:
            os.environ[POINTER_SKELETON_ENV] = original


@dataclass
class ArmResult:
    """一臂在一个 case 上的组装结果 + 分段度量。"""

    arm: str
    case_id: str
    messages: List[AgentMessage] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)

    @property
    def subgraph_text(self) -> str:
        for message in self.messages:
            content = message.content or ""
            if content.startswith("【会话记忆·相关子图】"):
                return content
        return ""


def _last_real_user_index(messages: Sequence[AgentMessage]) -> int:
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.role == "user" and not _is_injected_user_prompt(message.content):
            return index
    return -1


def _segment_metrics(messages: Sequence[AgentMessage], arm: str, case_id: str,
                     *, dropped: int = 0) -> Dict[str, Any]:
    semantic = tool_line = subgraph = 0
    pointer_lines = 0
    for message in messages:
        content = message.content or ""
        if content.startswith("【会话记忆·相关子图】"):
            subgraph += len(content)
        elif message.role == "tool":
            tool_line += len(content)
            if "候选指针" in content:
                pointer_lines += 1
        elif message.role in ("user", "assistant"):
            semantic += len(content)
    return {
        "arm": arm,
        "case_id": case_id,
        "total_est": (semantic + tool_line + subgraph) // 2,
        "semantic_est": semantic // 2,
        "tool_line_est": tool_line // 2,
        "subgraph_est": subgraph // 2,
        "pointer_lines": pointer_lines,
        "dropped_tool_messages": dropped,
        "messages": len(messages),
    }


def compose(case_id: str, question: str, messages: Sequence[AgentMessage], arm: str, *,
            budget_est: int = 16_000, graph: Optional[OfflineGraph] = None) -> ArmResult:
    """按臂组装 prompt 并回度量。

    ``messages`` 是「历史 + 本轮提问」的原始消息列表（tool 消息的 ``meta`` 已按内存态带 items）；
    ``budget_est`` 照 QA 档（``agent_configs._qa_budget_tokens_est`` 默认 16k）。
    """
    if arm not in ALL_ARMS:
        raise ValueError(f"未知臂: {arm!r}")
    source = list(messages)

    if arm in (ARM_A_MIN, ARM_POINTER):
        with pointer_switch(arm == ARM_POINTER):
            transformer = make_budget_transformer(max_tokens_est=budget_est, protect_current_run=True)
            composed = list(transformer(source))
        return ArmResult(arm=arm, case_id=case_id, messages=composed,
                         metrics=_segment_metrics(composed, arm, case_id))

    # —— 臂 3：证据层替换（历史 tool 原文移出 prompt，改由子图段承接）——
    graph = graph if graph is not None else build_graph(source)
    nodes = recall(graph, question)
    segment = render(nodes)
    last_user = _last_real_user_index(source)
    if not segment:
        # ⚠️ 护栏（2026-10-04 干跑实测得出）：图上没有可用节点时**不许移除证据**——
        # 否则臂 3 变成「丢了证据又没补上」（实测 D4：历史里没有一条被引用条款，
        # 移除后 prompt 从 13,248 est 掉到 164 est，等于裸答）。空图时退化为臂 1 行为。
        composed = list(source)
        return ArmResult(arm=arm, case_id=case_id, messages=composed,
                         metrics=_segment_metrics(composed, arm, case_id, dropped=0))
    kept: List[AgentMessage] = []
    dropped = 0
    for index, message in enumerate(source):
        if message.role == "tool" and last_user >= 0 and index < last_user:
            dropped += 1
            continue
        kept.append(message)
    anchor = _last_real_user_index(kept)
    injected = AgentMessage(role="user", content=segment)
    kept = kept[:anchor] + [injected] + kept[anchor:] if anchor >= 0 else kept + [injected]
    return ArmResult(arm=arm, case_id=case_id, messages=kept,
                     metrics=_segment_metrics(kept, arm, case_id, dropped=dropped))


def compose_all(case_id: str, question: str, messages: Sequence[AgentMessage], *,
                budget_est: int = 16_000) -> Dict[str, ArmResult]:
    """一次组装三臂（共用同一张离线图，保证臂间可比）。"""
    graph = build_graph(messages)
    return {
        arm: compose(case_id, question, messages, arm, budget_est=budget_est, graph=graph)
        for arm in ALL_ARMS
    }
