"""enum_prefetch：判定、开关/库白名单、裁剪与降级。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import enum_prefetch as ep  # noqa: E402


@pytest.mark.parametrize("query", [
    "pull every one of our antitrust matters where we drew an HSR second request",
    "list all our banking matters with secured credit facilities",
    "what are all our restructuring matters",
    "把涉及二次问询的案件全部列出来",
    "列出所有 HSR 案件",
])
def test_is_enumeration_positive(query):
    assert ep.is_enumeration(query)


@pytest.mark.parametrize("query", [
    "HSR 是什么？",
    "What is the HSR waiting period?",
    "A. 5 天 B. 10 天 C. 30 天 D. 60 天，选哪个？",
])
def test_is_enumeration_negative(query):
    assert not ep.is_enumeration(query)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ANGINEER_ENUM_PREFETCH", raising=False)
    assert not ep.enabled()
    assert ep.build_enum_context(query="list all our matters", library_id="lab-firm-full", llm=None) is None


def test_library_gate(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "lab-firm-full")
    assert ep.build_enum_context(query="list all our matters", library_id="std-water", llm=None) is None
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "*")
    # 库放开后仍取决于改写（llm=None 会抛错→降级）
    assert ep.build_enum_context(query="list all our matters", library_id="std-water", llm=None) is None


def test_rewrite_failure_degrades(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(ep, "rewrite_queries", lambda *a, **k: [])
    assert ep.build_enum_context(query="list all our matters", library_id="lib", llm=object()) is None


def test_context_is_capped(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(ep, "rewrite_queries", lambda *a, **k: ["q1", "q2"])
    matters = [
        {"matter_id": f"100{i:02d}-0000{j}", "best": {"title": f"doc-{i}-{j}.docx", "snippet": "x" * 200}}
        for i in range(10) for j in range(10)
    ]
    monkeypatch.setattr(ep, "_search_documents", lambda *a, **k: {"matters": matters, "total_matters": 100})
    text = ep.build_enum_context(query="list all our matters", library_id="lib", llm=object())
    assert text is not None
    assert len(text) <= ep.MAX_CHARS + 400
    assert text.count("\n- ") <= ep.MAX_CARDS
    assert "候选 matter 共 100 个" in text


def test_search_error_degrades(monkeypatch):
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(ep, "rewrite_queries", lambda *a, **k: ["q1"])

    def boom(*a, **k):
        raise RuntimeError("docs-api down")

    monkeypatch.setattr(ep, "_search_documents", boom)
    assert ep.build_enum_context(query="list all our matters", library_id="lib", llm=object()) is None
