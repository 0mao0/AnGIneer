"""answer_audit：开关、库白名单、guard 包装与降级。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import answer_audit as aa  # noqa: E402


class _Msg:
    def __init__(self, role: str, content: str, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def test_disabled_and_library_gate(monkeypatch):
    monkeypatch.delenv("ANGINEER_ANSWER_AUDIT", raising=False)
    assert not aa.enabled()
    monkeypatch.setenv("ANGINEER_ANSWER_AUDIT", "1")
    monkeypatch.setenv("ANGINEER_ANSWER_AUDIT_LIBRARIES", "lab-firm-full")
    assert aa.library_allowed("lab-firm-full")
    assert not aa.library_allowed("std-water")


def test_guard_degrades_without_llm(monkeypatch):
    monkeypatch.setattr(aa, "audit_answer", lambda *a, **k: None)
    guard = aa.make_audit_guard(None, llm=object(), question="list all matters", enabled_for_query=True)
    msgs = [_Msg("assistant", "final answer text")]
    assert guard(msgs) is None


def test_guard_replaces_answer(monkeypatch):
    monkeypatch.setattr(aa, "audit_answer", lambda *a, **k: "revised answer with exclusions")
    guard = aa.make_audit_guard(None, llm=object(), question="list all matters", enabled_for_query=True)
    msgs = [_Msg("assistant", "final answer text")]
    out = guard(msgs)
    assert out[0] == "revised answer with exclusions"
    assert out[2] == "answer_audited"


def test_guard_keeps_base_result(monkeypatch):
    monkeypatch.setattr(aa, "audit_answer", lambda *a, **k: None)

    def base(msgs):
        return ("base text", "base note", "no_evidence")

    guard = aa.make_audit_guard(base, llm=object(), question="q", enabled_for_query=True)
    assert guard([_Msg("assistant", "x")]) == ("base text", "base note", "no_evidence")


def test_guard_off_returns_base(monkeypatch):
    def base(msgs):
        return ("base", "n", "c")

    guard = aa.make_audit_guard(base, llm=object(), question="q", enabled_for_query=False)
    assert guard([_Msg("assistant", "x")]) == ("base", "n", "c")
