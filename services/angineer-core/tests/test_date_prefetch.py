"""date_prefetch：「最新/最近」判定、开关/库白名单、mtime 过滤、降级。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from angineer_core import date_prefetch as dp  # noqa: E402


@pytest.mark.parametrize("query", [
    "Pull the MFN provision from Lumos Analytics' most recent credit agreement",
    "What is the latest HSR filing we have?",
    "最近一次确认的重整计划是哪份",
    "哪一年开始用这个模板",
])
def test_is_date_query_positive(query):
    assert dp.is_date_query(query)


@pytest.mark.parametrize("query", [
    "What is the HSR waiting period?",
    "Summarize the credit agreement",
    "A. 5 天 B. 10 天 C. 30 天",
])
def test_is_date_query_negative(query):
    assert not dp.is_date_query(query)


def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("ANGINEER_DATE_PREFETCH", raising=False)
    assert not dp.enabled()
    assert dp.build_date_context(query="most recent credit agreement", library_id="lib") is None


def test_library_gate(monkeypatch):
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH_LIBRARIES", "lab-firm-full")
    assert dp.build_date_context(query="most recent credit agreement", library_id="std-water") is None
    assert dp.library_allowed("lab-firm-full")


def test_collect_drops_mtime_and_keeps_newest(monkeypatch):
    pytest.importorskip("docs_core")  # 该用例打桩 docs_core.search_documents，monorepo 外无此依赖
    from docs_core.step09_query import doc_search as ds

    calls = []

    def fake(**kwargs):
        calls.append(kwargs)
        assert kwargs["sort_by"] == "date_desc"
        return {
            "total_groups": 2,
            "matters": [
                {"group_id": "g1", "doc_date": "2024-01-01", "date_source": "text",
                 "date_confidence": "high", "best": {"title": "a.docx", "snippet": "a"}},
                {"group_id": "g1", "doc_date": "2025-01-01", "date_source": "text",
                 "date_confidence": "high", "best": {"title": "b.docx", "snippet": "b"}},
                {"group_id": "g2", "doc_date": "2026-01-01", "date_source": "mtime",
                 "date_confidence": "low", "best": {"title": "c.docx", "snippet": "c"}},
            ],
        }

    monkeypatch.setattr(ds, "search_documents", fake)
    cards, total = dp._collect("lib", ["q"])
    assert calls and calls[0]["library_id"] == "lib"
    assert total == 2
    assert [(c["group_id"], c["doc_date"], c["title"]) for c in cards] == [("g1", "2025-01-01", "b.docx")]


def test_build_context_injects_newest_first(monkeypatch):
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(dp, "rewrite_queries", lambda *a, **k: ["credit agreement latest"])
    cards = [
        {"group_id": "g2", "matter_id": "g2", "doc_date": "2025-06-01", "date_source": "text",
         "date_confidence": "high", "title": "new.docx", "snippet": "new"},
        {"group_id": "g1", "matter_id": "g1", "doc_date": "2024-01-01", "date_source": "text",
         "date_confidence": "medium", "title": "old.docx", "snippet": "old"},
    ]
    monkeypatch.setattr(dp, "_collect", lambda lib, qs: (cards, 3))
    text = dp.build_date_context(query="What is the most recent agreement?", library_id="lib", llm=object())
    assert text is not None
    assert "最新在前" in text
    assert text.index("2025-06-01") < text.index("2024-01-01")
    assert "候选组共 3 个" in text


def test_no_cards_degrades(monkeypatch):
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(dp, "rewrite_queries", lambda *a, **k: ["q"])
    monkeypatch.setattr(dp, "_collect", lambda lib, qs: ([], 0))
    assert dp.build_date_context(query="most recent agreement", library_id="lib", llm=object()) is None


def test_search_error_degrades(monkeypatch):
    pytest.importorskip("docs_core")  # 该用例打桩 docs_core.search_documents，monorepo 外无此依赖
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH", "1")
    monkeypatch.setenv("ANGINEER_DATE_PREFETCH_LIBRARIES", "*")
    monkeypatch.setattr(dp, "rewrite_queries", lambda *a, **k: ["q"])

    def boom(**kwargs):
        raise RuntimeError("docs-api down")

    from docs_core.step09_query import doc_search as ds

    monkeypatch.setattr(ds, "search_documents", boom)
    assert dp.build_date_context(query="most recent agreement", library_id="lib", llm=object()) is None


def test_context_is_capped(monkeypatch):
    cards = [
        {"group_id": f"g{i}", "matter_id": f"g{i}", "doc_date": "2025-01-01", "date_source": "text",
         "date_confidence": "high", "title": f"doc-{i}.docx", "snippet": "x" * 200}
        for i in range(40)
    ]
    text = dp.format_context(cards, 40, ["q"])
    assert len(text) <= dp.MAX_CHARS + 800
    assert text.count("\n- ") <= dp.MAX_CARDS


def test_prefetch_prefers_enumeration_then_date(monkeypatch):
    from angineer_core import agent_policy as ap

    monkeypatch.setattr(ap, "_enum_context", lambda *a: "ENUM")
    monkeypatch.setattr(ap, "_date_context", lambda *a: "DATE")
    assert ap._prefetch_context("q", "lib", object(), None, "instruct") == "ENUM"
    monkeypatch.setattr(ap, "_enum_context", lambda *a: None)
    assert ap._prefetch_context("q", "lib", object(), None, "instruct") == "DATE"
