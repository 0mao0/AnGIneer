"""证据指针 + 激进压缩（eager compress）机制测试。

背景（2026-10-06）：
- 预算压缩把跨 run 工具结果压成摘要行时保留 doc 指针（K 号·文档名·doc_id），
  knowledge_search 对 LLM 开放 doc_ids 入参，模型可按指针回看原文（VISTA inspect 语义）。
- ANGINEER_EAGER_COMPRESS 开启后不再等预算阈值，每轮即压「最后一条 user 之前」的
  跨 run 工具结果；当 run 证据（最后一条 user 之后）任何模式下都不压。

锁的行为：
- T1 指针格式：摘要行带 [doc_id=...]、按 doc 去重、≤6 条；
- T2 eager 边界：未超阈值也压跨 run 证据（关=不动，回归现状）；
- T3 当 run 豁免：超阈值 + eager 也不碰最后一条 user 之后的证据；
- T4 机制链路：run_agent_loop 全程跑通，压缩指针行真的进到发给 LLM 的 messages，
  且 session history 本体不被改写（投影式）；
- T5 doc_ids 入参：LLM 侧 args 的 doc_ids 覆盖构造绑定值，缺省回退绑定值。
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from angineer_core import agent_tools
from angineer_core.agent_configs import _summarize_tool_raw, make_budget_transformer
from angineer_core.agent_loop import AgentLoopConfig, run_agent_loop
from angineer_core.agent_messages import AgentMessage
from angineer_core.agent_tools import RetrieverAdapter
from angineer_core.tool_codec import TextToolCallCodec


def _item(doc_id, title, cite, page=1, text="证据正文片段"):
    return {
        "item_id": f"i-{cite}",
        "chunk_id": f"c-{cite}",
        "doc_id": doc_id,
        "doc_title": title,
        "page": page,
        "section_path": "",
        "score": 0.9,
        "text": text,
        "metadata": {"cite": cite},
    }


def _meta(items):
    return {"raw": {"items": items}}


def _tool_message(name, content, items):
    return AgentMessage(role="tool", name=name, content=content, meta=_meta(items))


# ---------- T1 指针格式 ----------


def test_pointer_line_contains_doc_id_and_dedup():
    """同 doc 多 chunk 只留一个指针；不同 doc 各留一个。"""
    meta = _meta(
        [
            _item("d1", "海港总体设计规范", "K1", text="a" * 100),
            _item("d1", "海港总体设计规范", "K2", text="b" * 100),
            _item("d2", "防波堤设计与施工规范", "K3", text="c" * 100),
        ]
    )
    summary = _summarize_tool_raw(meta)
    assert summary.count("d1") == 1
    assert "[doc_id=d1]" in summary
    assert "[doc_id=d2]" in summary
    assert "K1" in summary
    assert "K3" in summary


def test_pointer_line_caps_at_six():
    items = [_item(f"d{i}", f"规范{i}", f"K{i}") for i in range(8)]
    summary = _summarize_tool_raw(_meta(items))
    assert summary.count("[doc_id=") == 6


def test_no_raw_meta_falls_back_to_size_line():
    assert _summarize_tool_raw({"raw": "x" * 42}) == "x" * 42
    assert _summarize_tool_raw({}) == "{}"


# ---------- T2/T3 eager 边界 ----------


def _two_run_messages():
    return [
        AgentMessage(role="user", content="第一轮问题"),
        _tool_message(
            "knowledge_search",
            "第一轮证据原文" * 50,
            [_item("d1", "海港总体设计规范", "K1")],
        ),
        AgentMessage(role="assistant", content="第一轮回答[K1]"),
        AgentMessage(role="user", content="第二轮问题"),
        _tool_message(
            "knowledge_search",
            "第二轮当 run 证据必须完整保留",
            [_item("d2", "防波堤设计与施工规范", "K3")],
        ),
    ]


def test_eager_compresses_cross_run_under_budget():
    """eager 开：未超阈值也压跨 run 证据，当 run 证据与 history 本体不动。"""
    messages = _two_run_messages()
    transform = make_budget_transformer(max_tokens_est=100_000, protect_current_run=True, eager=True)
    result = transform(messages)
    assert result[1].content.startswith("[已压缩")
    assert "[doc_id=d1]" in result[1].content
    assert result[4].content == "第二轮当 run 证据必须完整保留"
    assert result[2].content == "第一轮回答[K1]"
    assert messages[1].content == "第一轮证据原文" * 50


def test_threshold_mode_leaves_history_under_budget():
    """回归：eager 关且未超阈值时原样返回（现状不变）。"""
    messages = _two_run_messages()
    transform = make_budget_transformer(max_tokens_est=100_000, protect_current_run=True, eager=False)
    result = transform(messages)
    assert result is messages


def test_eager_never_touches_current_run_even_over_budget():
    """超阈值 + eager：当 run 证据（最后一条 user 之后）仍然豁免。"""
    messages = _two_run_messages()
    transform = make_budget_transformer(max_tokens_est=1, protect_current_run=True, eager=True)
    result = transform(messages)
    assert result[1].content.startswith("[已压缩")
    assert result[4].content == "第二轮当 run 证据必须完整保留"


def test_eager_first_run_is_noop():
    """首轮（最后一条 user 在 index 0）无跨 run 历史可压，原样返回。"""
    messages = [AgentMessage(role="user", content="第一个问题")]
    transform = make_budget_transformer(max_tokens_est=100_000, protect_current_run=True, eager=True)
    assert transform(messages) is messages


# ---------- T4 机制链路：压缩指针行进到 LLM 的 messages ----------


class _CaptureLLM:
    """mock LLMProvider：捕获每次调用的 messages，按队列回放回复文本。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.captured = []

    def chat_stream_events(self, messages, **kwargs):
        self.captured.append(messages)
        text = self.replies.pop(0) if self.replies else "……"
        for ch in text:
            yield {"type": "delta", "text": ch}
        yield {"type": "done", "finish_reason": "stop", "usage": {"prompt_tokens": 1}}


def test_compressed_pointer_reaches_llm_messages():
    """eager 开的 transform 挂进 run_agent_loop：发给 LLM 的消息里
    跨 run 证据被压成带指针的摘要行，原文不出现，history 本体不被改写。"""
    messages = [
        AgentMessage(role="user", content="第一轮问题"),
        _tool_message(
            "knowledge_search",
            "第一轮证据原文" * 50,
            [_item("d1", "海港总体设计规范", "K1")],
        ),
        AgentMessage(role="assistant", content="第一轮回答[K1]"),
        AgentMessage(role="user", content="第二轮问题"),
    ]
    llm = _CaptureLLM(["这是基于证据的回答。[K1]"])
    config = AgentLoopConfig(
        llm=llm,
        system_prompt="test",
        tools=[],
        codec=TextToolCallCodec(),
        max_turns=2,
        transform_context=make_budget_transformer(
            max_tokens_est=100_000, protect_current_run=True, eager=True
        ),
        followup_question=False,
    )
    run_agent_loop(messages, config)
    assert llm.captured, "LLM 应至少被调用一次"
    sent_text = "\n".join(str(m.get("content", "")) for m in llm.captured[0])
    assert "[doc_id=d1]" in sent_text
    assert "第一轮证据原文" not in sent_text
    assert messages[1].content == "第一轮证据原文" * 50


# ---------- T5 doc_ids 入参：LLM 侧值覆盖构造绑定值 ----------


class _Capture(Exception):
    pass


def test_llm_supplied_doc_ids_override_bound(monkeypatch):
    monkeypatch.delenv("ANGINEER_ROUTE_PARALLEL", raising=False)
    captured = []

    def fake_impl(**kwargs):
        captured.append(dict(kwargs))
        raise _Capture

    monkeypatch.setattr(agent_tools, "_run_knowledge_search_impl", fake_impl)
    tool = RetrieverAdapter.knowledge_search(library_id="default", doc_ids=["d0"])

    with pytest.raises(_Capture):
        tool.handler(query="q", doc_ids=["d1", "d2"])
    assert captured[0]["doc_ids"] == ["d1", "d2"]

    with pytest.raises(_Capture):
        tool.handler(query="q")
    assert captured[1]["doc_ids"] == ["d0"]


def test_doc_ids_in_parameters_schema():
    """schema 必须对 LLM 暴露 doc_ids（否则模型永远不知道能回看）。"""
    tool = RetrieverAdapter.knowledge_search(library_id="default")
    props = tool.parameters_schema.get("properties") or {}
    assert "doc_ids" in props
