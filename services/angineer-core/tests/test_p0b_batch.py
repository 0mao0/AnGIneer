"""P0b 确定性校验件三件套单测：⑤安全终态四 guard、③引用贯通、④FINAL 槽解析。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import aggregate_answer as aa  # noqa: E402
from angineer_core import agent_messages as am  # noqa: E402
from angineer_core import answer_audit  # noqa: E402
from angineer_core import enum_closed_set  # noqa: E402
from angineer_core import structured_answer as sa  # noqa: E402
from angineer_core.agent_loop import _apply_final_guard  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.enum_prefetch import format_preread_context  # noqa: E402
from angineer_core.policy_query import _extract_final_answer  # noqa: E402

CONTEXT = """## Pre-read evidence (system, deterministic)
Judge qualification ONLY from these excerpts.

### 1006-00001 | crestline.docx
Crestline Packaging signed a credit agreement in 2021 carrying an always-on financial maintenance covenant.

### 1010-00001 | arbor.docx
Arbor Health Tech filed a 2024 agreement; excerpt does not state its covenant terms.

CLOSED SET (only these matters may be asserted as qualifying): 1006-00001, 1010-00001
For each matter, assert it as qualifying only if its excerpt states the qualifying condition.
"""

SPEC016 = {
    "match": "maintenance covenant",
    "dims": [
        {"name": "year", "kind": "free", "pattern": "^(?:19|20)\\d{2}$", "fallback_value": "unknown"},
        {"name": "covenant", "kind": "enum",
         "buckets": ["always_on", "springing", "out_of_population", "unknown"],
         "fallback_value": "unknown"},
    ],
    "group_by": ["year"],
    "population_exclude": {"dim": "covenant", "value": "out_of_population"},
    "share": {"numerator_dim": "covenant", "numerator_value": "always_on",
              "denominator_exclude": [{"dim": "covenant", "value": "out_of_population"}]},
}


def _refusal():
    return ("抱歉，未检索到有效证据，无法给出结论。", "no evidence", "no_evidence")


# --- ⑤安全终态：四个 wrapper guard 统一不覆盖 ---


def test_struct_guard_safe_terminal(monkeypatch):
    monkeypatch.setenv("ANGINEER_ANSWER_STRUCT", "1")
    monkeypatch.setattr(sa, "structured_answer_ex", lambda *a, **k: ("RENDERED", []))
    guard = sa.make_struct_guard(lambda _m: _refusal(), llm=object(), question="q",
                                 enabled_for_query=True, evidence_context="x")
    assert guard([AgentMessage(role="assistant", content="draft")]) == _refusal()


def test_aggregate_guard_safe_terminal_and_unsupported_ref(monkeypatch):
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE", "1")
    monkeypatch.setattr(aa, "aggregate_answer_ex", lambda *a, **k: ("TABLE", []))
    aa._SPEC_CACHE.clear()
    base_unsupported = ("拒答", "fake ref", "unsupported_reference")
    for base in (_refusal(), base_unsupported):
        guard = aa.make_aggregate_guard(lambda _m: base, llm=object(), question="q",
                                        enabled_for_query=True, evidence_context="x")
        assert guard([AgentMessage(role="assistant", content="draft")]) == base


def test_closed_set_guard_safe_terminal():
    monkey_env = {"ANGINEER_ENUM_CLOSED_SET": "1"}
    # base 拒答文本即使含 matter 号也被 code 门挡住（旧行为靠内容门偶然不覆盖）
    base = ("抱歉，未检索到 1003-00001 的有效证据。", "no evidence", "no_evidence")
    guard = enum_closed_set.make_closed_set_guard(
        lambda _m: base, llm=object(), question="q", enabled_for_query=True,
        closed_set_context="### 1003-00001 | a.doc\n\nCLOSED SET: 1003-00001")
    orig = enum_closed_set.enabled
    try:
        enum_closed_set.enabled = lambda: True
        assert guard([AgentMessage(role="assistant", content=base[0])]) == base
    finally:
        enum_closed_set.enabled = orig


def test_audit_guard_safe_terminal():
    long_refusal = "抱歉，" + "未检索到有效证据。" * 40
    base = (long_refusal, "no evidence", "no_evidence")
    guard = answer_audit.make_audit_guard(
        lambda _m: base, llm=object(), question="q", enabled_for_query=True)
    orig = answer_audit.enabled
    try:
        answer_audit.enabled = lambda: True
        assert guard([AgentMessage(role="assistant", content=long_refusal)]) == base
    finally:
        answer_audit.enabled = orig


# --- ③引用贯通 ---


def test_format_preread_context_allocates_cites():
    class Alloc:
        def __init__(self):
            self.n = 0

        def next(self, prefix):
            self.n += 1
            return f"{prefix}{self.n}"

    ctx = format_preread_context(
        {"1006-00001": ("a.doc", "text one"), "1021-00001": ("b.doc", "text two")},
        {"1006-00001": "d1", "1021-00001": ["d2", "d3"]},
        library_id="lab", marker_allocator=Alloc())
    _, index = sa.split_preread_index(ctx)
    assert index["cites"] == {"1006-00001": "K1", "1021-00001": "K2"}
    assert index["doc_ids"]["1021-00001"] == ["d2", "d3"]
    # 无 allocator：不含 cites（向后兼容）
    ctx2 = format_preread_context({"1006-00001": ("a.doc", "t")}, {"1006-00001": "d1"})
    _, index2 = sa.split_preread_index(ctx2)
    assert "cites" not in (index2 or {})


def test_structured_render_and_citations_from_index(monkeypatch):
    idx = json.dumps({"library": "lab", "doc_ids": {"1006-00001": "doc-a"},
                      "cites": {"1006-00001": "K7"}}, separators=(",", ":"))
    ctx = CONTEXT + "\nPREREAD INDEX (system): " + idx

    class R:
        text = ("Q || 1006-00001 || crestline.docx || "
                "carrying an always-on financial maintenance covenant || always-on in 2021")

    monkeypatch.setattr(sa, "_chat", lambda llm, messages, **k: R())
    rendered, citations = sa.structured_answer_ex(object(), question="q", context=ctx)
    assert "[K7]" in rendered
    assert citations[0]["marker"] == "K7" and citations[0]["target_id"] == "doc-a"
    assert "PREREAD INDEX" not in json.dumps(citations)


def test_aggregate_render_and_citations(monkeypatch):
    idx = json.dumps({"library": "lab", "doc_ids": {"1006-00001": "doc-a"},
                      "cites": {"1006-00001": "K3"}}, separators=(",", ":"))
    ctx = CONTEXT + "\nPREREAD INDEX (system): " + idx

    class R:
        text = ("C || 1006-00001 || 2021 || always_on || "
                "carrying an always-on financial maintenance covenant || Crestline is always-on\n"
                "N || 1010-00001 || no covenant statement\n")

    monkeypatch.setattr(aa, "_chat", lambda llm, messages, **k: R())
    rendered, citations = aa.aggregate_answer_ex(
        object(), question="maintenance covenant", context=ctx, spec=dict(SPEC016))
    assert "- 1006-00001 | 2021 | always-on [K3]" in rendered
    # 兜底行不加标记
    detail = rendered.split("### Supporting detail")[1]
    assert "（兜底归类）[K" not in detail
    assert len(citations) == 1
    assert citations[0]["marker"] == "K3"
    assert citations[0]["target_id"] == "doc-a"
    assert "always-on financial maintenance covenant" in citations[0]["snippet"]


def test_apply_final_guard_stashes_guard_citations():
    citations = [{"target_id": "d1", "marker": "K1"}]

    def guard(_messages):
        return ("rendered", "note", "answer_structured", {"citations": citations})

    config = type("C", (), {"final_answer_guard": staticmethod(guard)})()
    messages = [AgentMessage(role="assistant", content="draft")]
    code = _apply_final_guard(config, messages, 0, None, "r", 1, lambda _n: None)
    assert code == "answer_structured"
    assert messages[0].meta["guard_citations"] == citations
    # 3 元组路径不挂 meta
    config3 = type("C", (), {"final_answer_guard": staticmethod(lambda _m: ("x", "n", "answer_structured"))})()
    messages3 = [AgentMessage(role="assistant", content="draft")]
    _apply_final_guard(config3, messages3, 0, None, "r", 1, lambda _n: None)
    assert "guard_citations" not in (messages3[0].meta or {})


def test_merge_and_collect_guard_citations():
    tool_cites = [{"target_id": "d9", "marker": "K9"}]
    guard_cites = [{"target_id": "d9", "marker": "K9"}, {"target_id": "d1", "marker": "K1"}]
    merged = am.merge_citations(tool_cites, guard_cites)
    assert len(merged) == 2 and merged[1]["marker"] == "K1"
    messages = [
        AgentMessage(role="tool", content="x", meta={"citations": tool_cites}),
        AgentMessage(role="assistant", content="a", meta={"guard_citations": guard_cites}),
    ]
    assert am.collect_guard_citations(messages) == guard_cites


# --- ④FINAL 槽解析 ---


def test_extract_final_answer_variants():
    assert _extract_final_answer("分析……\n**FINAL: 42.3**") == "42.3"
    assert _extract_final_answer("……\nFinal Answer: 1,234") == "1,234"
    assert _extract_final_answer("……\nFINAL：约 7 天") == "约 7 天"
    assert _extract_final_answer("普通答案无协议") is None
    assert _extract_final_answer("") is None
