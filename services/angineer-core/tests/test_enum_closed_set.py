"""enum_closed_set：闭集判定、降级与 guard 包装。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import enum_closed_set as ecs  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402


def _tool(name: str, payload, is_error: bool = False) -> AgentMessage:
    return AgentMessage(role="tool", name=name, content=json.dumps(payload), is_error=is_error)


def _final(text: str) -> AgentMessage:
    return AgentMessage(role="assistant", content=text)


def test_collect_read_matters_only_from_doc_read():
    msgs = [
        _tool("doc_read", {"docs": [{"matter_id": "1003-00001"}, {"matter_id": "1038-00001"}]}),
        _tool("doc_search", {"matters": [{"matter_id": "1041-00001"}]}),  # 不算
        _tool("doc_read", {"docs": [{"matter_id": "1001-00001"}]}, is_error=True),  # 失败不算
    ]
    assert ecs.collect_read_matters(msgs) == {"1003-00001", "1038-00001"}


def test_collect_read_matters_regex_fallback():
    msgs = [AgentMessage(role="tool", name="doc_read", content="read 1003-00003 page 1")]
    assert ecs.collect_read_matters(msgs) == {"1003-00003"}


def test_unbacked_matters():
    answer = "Matters: 1003-00001, 1038-00009 and 1001-00004."
    assert ecs.unbacked_matters(answer, {"1003-00001", "1001-00004"}) == ["1038-00009"]
    assert ecs.unbacked_matters(answer, {"1003-00001", "1038-00009", "1001-00004"}) == []


def _guard(monkeypatch, llm_text="revised answer " * 20):
    calls = []

    def fake_rewrite(llm, *, question, answer, supported, unbacked, config_name=None, mode="instruct"):
        calls.append((sorted(supported), list(unbacked)))
        return llm_text

    monkeypatch.setattr(ecs, "rewrite_answer", fake_rewrite)
    return calls


def test_guard_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ANGINEER_ENUM_CLOSED_SET", raising=False)
    calls = _guard(monkeypatch)
    guard = ecs.make_closed_set_guard(None, llm=object(), question="q", enabled_for_query=True)
    msgs = [_tool("doc_read", {"docs": []}), _final("assert 1038-00009")]
    assert guard(msgs) is None
    assert not calls


def test_guard_no_unbacked_keeps_answer(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_CLOSED_SET", "1")
    calls = _guard(monkeypatch)
    guard = ecs.make_closed_set_guard(None, llm=object(), question="q", enabled_for_query=True)
    msgs = [
        _tool("doc_read", {"docs": [{"matter_id": "1038-00009"}]}),
        _final("We handled matter 1038-00009."),
    ]
    assert guard(msgs) is None
    assert not calls


def test_guard_rewrites_unbacked(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_CLOSED_SET", "1")
    calls = _guard(monkeypatch)
    guard = ecs.make_closed_set_guard(None, llm=object(), question="q", enabled_for_query=True)
    msgs = [
        _tool("doc_read", {"docs": [{"matter_id": "1003-00001"}]}),
        _final("Matters 1003-00001 and 1038-00009 qualify."),
    ]
    result = guard(msgs)
    assert result is not None
    assert result[2] == "enum_closed_set"
    assert calls == [(["1003-00001"], ["1038-00009"])]


def test_guard_rewrite_failure_keeps_answer(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_CLOSED_SET", "1")
    monkeypatch.setattr(ecs, "rewrite_answer", lambda *a, **k: None)
    guard = ecs.make_closed_set_guard(None, llm=object(), question="q", enabled_for_query=True)
    msgs = [
        _tool("doc_read", {"docs": []}),
        _final("Matters 1038-00009 qualify."),
    ]
    assert guard(msgs) is None


def test_allowed_from_context():
    ctx = "some text\nCLOSED SET (only these matters may be asserted as qualifying): 1003-00001, 1038-00001\nTail"
    assert ecs.allowed_from_context(ctx) == {"1003-00001", "1038-00001"}
    assert ecs.allowed_from_context("no closed set here") == set()


def test_guard_uses_preread_context(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_CLOSED_SET", "1")
    calls = _guard(monkeypatch)
    guard = ecs.make_closed_set_guard(
        None, llm=object(), question="q", enabled_for_query=True,
        closed_set_context="CLOSED SET: 1003-00001",
    )
    msgs = [_final("Matters 1003-00001 and 1038-00009 qualify.")]
    result = guard(msgs)
    assert result is not None and result[2] == "enum_closed_set"
    assert calls == [(["1003-00001"], ["1038-00009"])]
