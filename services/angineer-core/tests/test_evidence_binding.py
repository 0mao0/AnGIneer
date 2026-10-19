"""evidence_binding：证据收集、引文核验、无依据句子剔除、guard 降级。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import evidence_binding as eb  # noqa: E402


class _Msg:
    def __init__(self, role, content, tool_calls=None):
        self.role = role
        self.content = content
        self.tool_calls = tool_calls


def _tool(payload):
    return _Msg("tool", json.dumps(payload))


TEXT = (
    "On July 16, 2024, the FTC issued a Second Request to 1038-00001 Cascade Retail "
    "in connection with its proposed acquisition of TargetCo."
)


def test_collect_evidence_shapes():
    msgs = [
        _tool({"items": [{"doc_id": "d1", "text": TEXT}]}),
        _tool({"docs": [{"doc_id": "d2", "text": "Another document body with enough text to be usable."}]}),
        _tool({"matters": [{"matter_id": "1003-00001", "best": {"doc_id": "d3", "snippet": "Snippet text"}}]}),
        _Msg("assistant", "answer"),
    ]
    ev = eb.collect_evidence(msgs)
    assert [e["doc_id"] for e in ev] == ["d1", "d2", "d3"]


def test_quote_supported():
    ev = [{"doc_id": "d1", "text": TEXT}]
    assert eb.quote_supported(TEXT[:80], ev)
    assert not eb.quote_supported(TEXT[:20], ev)  # 太短
    assert not eb.quote_supported("A totally different sentence that is long enough to pass length.", ev)


def test_quote_supported_ellipsis():
    ev = [{"doc_id": "d1", "text": TEXT}]
    quote = "On July 16, 2024, the FTC issued a Second Request … in connection with its proposed acquisition"
    assert eb.quote_supported(quote, ev)


def test_verify_and_strip():
    ev = [{"doc_id": "d1", "text": TEXT}]
    claims = [
        {"claim": "FTC issued a Second Request to 1038-00001", "quote": TEXT[:70]},
        {"claim": "Matter 1041-00001 closed in 2020", "quote": "Not in evidence at all, this is a fabricated quote."},
    ]
    verified = eb.verify_claims(claims, ev)
    assert verified[0]["supported"] and not verified[1]["supported"]
    answer = "FTC issued a Second Request to 1038-00001 in July 2024.\n\nMatter 1041-00001 closed in 2020."
    new, removed = eb.strip_unsupported(answer, verified)
    assert removed == 1
    assert "1041-00001" not in new
    assert "1038-00001" in new


def test_parse_and_verify_citations():
    answer = "Deal A drew a Second Request [d1 p3]. Deal B did not [d9 p1]."
    cites = eb.parse_citations(answer)
    assert cites == [{"doc_id": "d1", "page": "3"}, {"doc_id": "d9", "page": "1"}]
    stats = eb.verify_citations(answer, [{"doc_id": "d1", "text": TEXT}])
    assert stats["total"] == 2 and stats["valid"] == 1 and stats["invalid"] == 1


def test_contract_mode_does_not_rewrite(monkeypatch):
    monkeypatch.setenv("ANGINEER_EVIDENCE_CONTRACT", "1")
    assert eb.contract_enabled()
    guard = eb.make_guard(None, llm=object())
    msgs = [_Msg("assistant", "Deal A [d1 p3]."), _tool({"items": [{"doc_id": "d1", "text": TEXT}]})]
    assert guard(msgs) is None  # 契约模式只核验，不改写


def test_guard_degrades_without_claims(monkeypatch):
    monkeypatch.setattr(eb, "audit_answer", lambda *a, **k: {"claims": [], "supported": 0, "unsupported": 0})
    guard = eb.make_guard(None, llm=object())
    msgs = [_Msg("assistant", "A normal answer with enough content.")]
    assert guard(msgs) is None
