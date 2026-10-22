"""structured_answer：预读切块、JSON 解析、引文校验与渲染。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import structured_answer as sa  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402

CONTEXT = """## Pre-read evidence (system, deterministic)
Judge qualification ONLY from these excerpts.

### 1003-00001 | memo.docx
The firm received a second request from the DOJ on 2025-05-08.

### 1038-00001 | spa.docx
Section 6.03 HSR Act filings; no second request was issued.

CLOSED SET (only these matters may be asserted as qualifying): 1003-00001, 1038-00001
For each matter, assert it as qualifying only if its excerpt states the qualifying condition.
"""


def test_evidence_blocks():
    blocks = sa.evidence_blocks(CONTEXT)
    assert set(blocks) == {"1003-00001", "1038-00001"}
    assert blocks["1003-00001"]["title"] == "memo.docx"
    assert "second request" in blocks["1003-00001"]["text"]
    assert "CLOSED SET" not in blocks["1038-00001"]["text"]


def test_closed_set_from_context():
    assert sa.closed_set_from_context(CONTEXT) == ["1003-00001", "1038-00001"]


def test_parse_structured_with_fence():
    data = sa.parse_structured('```json\n{"qualifying": [], "not_qualified": []}\n```')
    assert data == {"qualifying": [], "not_qualified": []}
    assert sa.parse_structured("no json") is None


def test_validate_rows_quote_containment():
    blocks = sa.evidence_blocks(CONTEXT)
    data = {
        "qualifying": [
            {"matter_id": "1003-00001", "document": "memo.docx",
             "quote": "received a second request from the DOJ"},
            {"matter_id": "1038-00001", "document": "spa.docx",
             "quote": "received a second request"},  # 摘录里没有
        ],
        "not_qualified": [{"matter_id": "1038-00001", "reason": "no second request"}],
    }
    result = sa.validate_rows(data, blocks, sa.closed_set_from_context(CONTEXT))
    assert [r["matter_id"] for r in result["qualifying"]] == ["1003-00001"]
    assert result["rejected"][0]["matter_id"] == "1038-00001"
    assert result["not_qualified"][0]["matter_id"] == "1038-00001"


def test_render_answer():
    text = sa.render_answer({
        "qualifying": [{"matter_id": "1003-00001", "document": "memo.docx", "quote": "q" * 30}],
        "not_qualified": [{"matter_id": "1038-00001", "reason": "no second request"}],
        "rejected": [],
    })
    assert "1003-00001" in text and "memo.docx" in text
    assert "Not qualified" in text and "1038-00001" in text


def test_struct_guard_replaces_answer(monkeypatch):
    monkeypatch.setenv("ANGINEER_ANSWER_STRUCT", "1")
    monkeypatch.setattr(sa, "structured_answer", lambda *a, **k: "RENDERED")
    guard = sa.make_struct_guard(None, llm=object(), question="q", enabled_for_query=True,
                                 evidence_context=CONTEXT)
    result = guard([AgentMessage(role="assistant", content="draft")])
    assert result[0] == "RENDERED" and result[2] == "answer_structured"


def test_struct_guard_disabled(monkeypatch):
    monkeypatch.delenv("ANGINEER_ANSWER_STRUCT", raising=False)
    guard = sa.make_struct_guard(None, llm=object(), question="q", enabled_for_query=True,
                                 evidence_context=CONTEXT)
    assert guard([AgentMessage(role="assistant", content="draft")]) is None


def test_struct_guard_failure_keeps_original(monkeypatch):
    monkeypatch.setenv("ANGINEER_ANSWER_STRUCT", "1")
    monkeypatch.setattr(sa, "structured_answer", lambda *a, **k: None)
    guard = sa.make_struct_guard(None, llm=object(), question="q", enabled_for_query=True,
                                 evidence_context=CONTEXT)
    assert guard([AgentMessage(role="assistant", content="draft")]) is None


def test_multi_quote_and_finding_merge():
    blocks = sa.evidence_blocks(CONTEXT)
    data = {
        "qualifying": [
            {"matter_id": "1003-00001", "document": "memo.docx",
             "quotes": ["received a second request from the DOJ", "The firm received a second request"],
             "finding": "Received a DOJ second request."},
            {"matter_id": "1003-00001", "document": "notice.docx",
             "quotes": ["received a second request from the DOJ"]},
        ],
        "not_qualified": [],
    }
    result = sa.validate_rows(data, blocks, sa.closed_set_from_context(CONTEXT))
    assert len(result["qualifying"]) == 1
    row = result["qualifying"][0]
    assert row["finding"] == "Received a DOJ second request."
    assert "memo.docx" in row["documents"] and "notice.docx" in row["documents"]
    text = sa.render_answer(result)
    assert "**Finding:**" in text
    assert text.count("> ") == 2


def test_parse_lines_format():
    raw = ("Q || 1003-00001 || memo.docx || The firm received a second request from the DOJ || Received a DOJ second request.\n"
           "Q || 1003-00001 || memo2.docx || received a second request from the DOJ || Same fact, second document.\n"
           "N || 1038-00001 || no second request in the agreement\n")
    data = sa.parse_lines(raw)
    assert len(data["qualifying"]) == 2
    assert data["not_qualified"][0]["matter_id"] == "1038-00001"
    result = sa.validate_rows(data, sa.evidence_blocks(CONTEXT), sa.closed_set_from_context(CONTEXT))
    assert len(result["qualifying"]) == 1
    assert result["qualifying"][0]["finding"] == "Received a DOJ second request."
    assert "memo.docx" in result["qualifying"][0]["documents"]


def test_quote_matching_tolerates_punctuation():
    blocks = sa.evidence_blocks(CONTEXT)
    data = {"qualifying": [{
        "matter_id": "1003-00001", "document": "memo.docx",
        "quotes": ['received a "second request" from the D.O.J.'],
        "finding": "x",
    }], "not_qualified": []}
    result = sa.validate_rows(data, blocks, sa.closed_set_from_context(CONTEXT))
    assert len(result["qualifying"]) == 1


def test_parse_lines_single_pipe():
    raw = ("Q || 1003-00001 | memo.docx | received a second request from the DOJ | finding\n"
           "N | 1038-00001 | no second request\n")
    data = sa.parse_lines(raw)
    assert data["qualifying"][0]["matter_id"] == "1003-00001"
    assert data["qualifying"][0]["document"] == "memo.docx"
    assert data["not_qualified"][0]["matter_id"] == "1038-00001"
