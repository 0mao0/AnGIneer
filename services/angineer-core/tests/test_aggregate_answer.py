"""aggregate_answer（S2 聚合臂）：归类行解析、校验兜底、确定性计数、渲染与 guard 三态。

纯函数为主，无 LLM；guard 测试 monkeypatch 模块内 aggregate_answer（套路同 test_structured_answer.py）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import aggregate_answer as aa  # noqa: E402
from angineer_core.agent_messages import AgentMessage  # noqa: E402
from angineer_core.structured_answer import closed_set_from_context, evidence_blocks  # noqa: E402

CONTEXT = """## Pre-read evidence (system, deterministic)
Judge qualification ONLY from these excerpts.

### 1006-00001 | crestline.docx
Crestline Packaging signed a credit agreement in 2021 carrying an always-on financial maintenance covenant.

### 1021-00001 | verimark.docx
Verimark Hospitality entered a 2022 facility whose only financial covenant is springing.

### 1042-00001 | brightfield.docx
Brightfield Cloud completed a 2022 financing carrying always-on financial maintenance covenants.

### 1008-00001 | lumos.docx
Lumos Analytics signed a 2023 facility with a springing covenant only.

### 1012-00001 | stonefield.docx
Stonefield Logistics signed a 2023 financing carrying always-on financial maintenance covenants.

### 1036-00001 | fairwater-reit.docx
Fairwater REIT is a 2025 real-estate-secured financing outside the credit-facility scope.

### 1010-00001 | arbor.docx
Arbor Health Tech filed a 2024 agreement; excerpt does not state its covenant terms.

CLOSED SET (only these matters may be asserted as qualifying): 1006-00001, 1021-00001, 1042-00001, 1008-00001, 1012-00001, 1036-00001, 1010-00001
For each matter, assert it as qualifying only if its excerpt states the qualifying condition.
"""

SPEC016 = {
    "match": "maintenance covenant",
    "question_hint": "harvey-fk-016",
    "dims": [
        {"name": "year", "kind": "free", "pattern": r"^(?:19|20)\d{2}$",
         "fallback_value": "unknown",
         "prompt_hint": "the year the credit agreement was signed (4-digit year)"},
        {"name": "covenant", "kind": "enum",
         "buckets": ["always_on", "springing", "out_of_population", "unknown"],
         "fallback_value": "unknown",
         "prompt_hint": "springing covenants stay in the population but never count as maintenance"},
    ],
    "group_by": ["year"],
    "population_exclude": {"dim": "covenant", "value": "out_of_population"},
    "share": {"numerator_dim": "covenant", "numerator_value": "always_on",
              "denominator_exclude": [{"dim": "covenant", "value": "out_of_population"}]},
}

SPEC041 = {
    "match": "lead underwriters",
    "question_hint": "harvey-fk-041",
    "dims": [
        {"name": "underwriter", "kind": "entity", "fallback_value": "unclassified",
         "prompt_hint": "the lead underwriter (lead bank) of the mandate, exactly as written in the excerpt",
         "prompt_extra": ("Different firms with similar names are DIFFERENT entities — never merge them; "
                          "if the matter had no underwriter, use no_underwriter")},
    ],
    "group_by": ["underwriter"],
}

BLOCKS = evidence_blocks(CONTEXT)
CLOSED = closed_set_from_context(CONTEXT)


# --- 判定与解析 ---


def test_is_aggregation_patterns():
    assert aa.is_aggregation("track how the share of our financings has moved year over year")
    assert aa.is_aggregation("break down the lead underwriters we've worked with and how often each one shows up")
    assert aa.is_aggregation("How many matters involved a second request?")
    assert not aa.is_aggregation("What is the filing deadline for HSR second requests?")


def test_parse_cls_lines_positional_and_errors():
    raw = (
        "C || 1006-00001 || 2021 || always_on || carrying an always-on financial maintenance covenant || Crestline is always-on\n"
        "C || 1006-00001 || || always_on || q || empty year field\n"
        "N || 1010-00001 || excerpt does not state covenant terms\n"
        "C || 1012-00001 || 2023\n"
    )
    parsed = aa.parse_cls_lines(raw, n_dims=2)
    assert parsed["classified"][0]["matter_id"] == "1006-00001"
    assert parsed["classified"][0]["values"] == ["2021", "always_on"]
    # 空字段保位：year 为空串 → 校验层拒
    assert parsed["classified"][1]["values"][0] == ""
    # 字段数不足 → 归入 unclassified（走兜底）
    assert parsed["unclassified"][-1]["matter_id"] == "1012-00001"
    assert parsed["unclassified"][0]["matter_id"] == "1010-00001"


# --- 校验与兜底 ---


def test_classify_quote_containment_and_backstop():
    parsed = aa.parse_cls_lines(
        "C || 1006-00001 || 2021 || always_on || carrying an always-on financial maintenance covenant || Crestline is always-on\n"
        "C || 1042-00001 || 2022 || always_on || signed a 2021 facility || wrong quote not in excerpt\n"
        "N || 1010-00001 || excerpt does not state covenant terms\n",
        n_dims=2,
    )
    result = aa.classify(SPEC016, parsed, BLOCKS, CLOSED)
    cls = result["classifications"]
    # 命中：闭集内 + 引文在场
    assert cls["1006-00001"]["values"] == ["2021", "always_on"]
    # 引文不在场 → 拒 → 完备性兜底
    assert any(r["matter_id"] == "1042-00001" for r in result["rejected"])
    assert cls["1042-00001"]["backstop"] is True
    assert cls["1042-00001"]["values"] == ["unknown", "unknown"]
    # N 行 → 兜底
    assert cls["1010-00001"]["backstop"] is True
    # 完备性：候选全集内每个 matter 都有归类
    assert set(cls) == set(CLOSED)


def test_classify_rejects_out_of_closed_set_and_bad_bucket():
    parsed = aa.parse_cls_lines(
        "C || 9999-99999 || 2021 || always_on || q || outside set\n"
        "C || 1006-00001 || 2021 || quarterly_only || carrying an always-on financial maintenance covenant || bad bucket\n",
        n_dims=2,
    )
    result = aa.classify(SPEC016, parsed, BLOCKS, CLOSED)
    reasons = {r["matter_id"]: r["reason"] for r in result["rejected"]}
    assert "不在预读允许集" in reasons["9999-99999"]
    assert "维度值不在桶清单" in reasons["1006-00001"]


def test_classify_entity_casefold_merges_but_near_names_stay_apart():
    parsed = aa.parse_cls_lines(
        "C || 1006-00001 || Pinnacle Securities LLC || carrying an always-on financial maintenance covenant || q1\n"
        "C || 1021-00001 || pinnacle securities llc || entered a 2022 facility whose only financial covenant is springing || q2\n"
        "C || 1042-00001 || Pinnacle Zanthor & Co. || completed a 2022 financing carrying always-on financial maintenance covenants || q3\n"
        "N || 1010-00001 || no underwriter stateable\n",
        n_dims=1,
    )
    result = aa.classify(SPEC041, parsed, BLOCKS, CLOSED)
    aggregate = aa.compute_aggregate(SPEC041, result)
    counts = {(r["group"]["underwriter"], r["count"]) for r in aggregate["table_rows"]}
    # 大小写变体合并（分组键 casefold，展示名取首见原串）；近似名不合并（Distinct from）；N 行进 unclassified 兜底
    assert (("Pinnacle Securities LLC", 2)) in counts
    assert (("Pinnacle Zanthor & Co.", 1)) in counts
    # 完备性兜底：N 行 1 个 + 无归类行 3 个（1008/1012/1036）= 4
    assert any(name == "unclassified" and count == 4 for name, count in counts)


# --- 确定性计数 ---


def test_compute_aggregate_016_share_matrix():
    parsed = aa.parse_cls_lines(
        "C || 1006-00001 || 2021 || always_on || carrying an always-on financial maintenance covenant || q\n"
        "C || 1021-00001 || 2022 || springing || whose only financial covenant is springing || q\n"
        "C || 1042-00001 || 2022 || always_on || carrying always-on financial maintenance covenants || q\n"
        "C || 1008-00001 || 2023 || springing || with a springing covenant only || q\n"
        "C || 1012-00001 || 2023 || always_on || carrying always-on financial maintenance covenants || q\n"
        "C || 1036-00001 || 2025 || out_of_population || real-estate-secured financing outside the credit-facility scope || q\n"
        "N || 1010-00001 || excerpt does not state covenant terms\n",
        n_dims=2,
    )
    result = aa.classify(SPEC016, parsed, BLOCKS, CLOSED)
    aggregate = aa.compute_aggregate(SPEC016, result)
    rec = aggregate["reconciliation"]
    assert (rec["candidates_n"], rec["population_n"], rec["excluded_n"]) == (7, 6, 1)
    assert rec["complete"] is True and rec["counts_sum_matches"] is True
    assert rec["backstop_n"] == 1
    shares = {tuple(sorted(r["group"].items())): r["share"] for r in aggregate["share_rows"]}
    assert shares[(("year", "2021"),)] == "1/1 (100%)"
    assert shares[(("year", "2022"),)] == "1/2 (50%)"
    # 夹具里 2023 只有 2 个已归类 matter（1010 兜底进 unknown 年份行），故 1/2
    assert shares[(("year", "2023"),)] == "1/2 (50%)"
    # out_of_population 出分母、不出现在份额；unknown 兜底行留在分母
    assert shares[(("year", "unknown"),)] == "0/1 (0%)"
    assert not any("out-of-population" in str(r["group"]) for r in aggregate["share_rows"])


def test_render_answer_contains_table_recon_and_gap_note():
    parsed = aa.parse_cls_lines(
        "C || 1006-00001 || 2021 || always_on || carrying an always-on financial maintenance covenant || Crestline 2021 always-on\n"
        "C || 1021-00001 || 2022 || springing || whose only financial covenant is springing || Verimark springing\n"
        "N || 1010-00001 || excerpt does not state covenant terms\n",
        n_dims=2,
    )
    result = aa.classify(SPEC016, parsed, BLOCKS, CLOSED)
    aggregate = aa.compute_aggregate(SPEC016, result)
    text = aa.render_answer(SPEC016, result, aggregate)
    assert "Aggregate result" in text
    assert "| year | share (numerator/population) |" in text
    assert "1/1 (100%)" in text
    assert "### Reconciliation" in text
    assert "candidate set ≠ gold population" in text
    assert "classification complete: yes" in text
    assert "（兜底归类）" in text


# --- 配置加载 ---


def test_load_spec_match_and_missing(tmp_path, monkeypatch):
    spec_file = tmp_path / "specs.json"
    spec_file.write_text(json.dumps({"specs": [SPEC016, SPEC041]}), encoding="utf-8")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(spec_file))
    aa._SPEC_CACHE.clear()
    spec = aa.load_spec("A client wants a market read on maintenance covenants before negotiation")
    assert spec["question_hint"] == "harvey-fk-016"
    assert aa.load_spec("plain question about nothing matching") is None


def test_load_spec_bad_path_returns_none(tmp_path, monkeypatch):
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(tmp_path / "nope.json"))
    aa._SPEC_CACHE.clear()
    assert aa.load_spec("any question") is None


# --- guard 三态 ---


Q016 = "track how the share of our maintenance covenant financings has moved year over year"


def test_guard_replaces_with_aggregate(monkeypatch, tmp_path):
    spec_file = tmp_path / "specs.json"
    spec_file.write_text(json.dumps({"specs": [SPEC016]}), encoding="utf-8")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE", "1")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(spec_file))
    monkeypatch.setattr(aa, "aggregate_answer", lambda *a, **k: "AGG_TABLE")
    aa._SPEC_CACHE.clear()
    guard = aa.make_aggregate_guard(None, llm=object(), question=Q016,
                                    enabled_for_query=True, evidence_context=CONTEXT)
    result = guard([AgentMessage(role="assistant", content="draft")])
    assert result[0] == "AGG_TABLE" and result[2] == "answer_aggregate"


def test_guard_safe_terminal_not_overridden(monkeypatch, tmp_path):
    spec_file = tmp_path / "specs.json"
    spec_file.write_text(json.dumps({"specs": [SPEC016]}), encoding="utf-8")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE", "1")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(spec_file))
    monkeypatch.setattr(aa, "aggregate_answer", lambda *a, **k: "AGG_TABLE")
    aa._SPEC_CACHE.clear()

    def base_guard(_messages):
        return ("拒答：无证据", "no evidence", "no_evidence")

    guard = aa.make_aggregate_guard(base_guard, llm=object(), question=Q016,
                                    enabled_for_query=True, evidence_context=CONTEXT)
    result = guard([AgentMessage(role="assistant", content="draft")])
    # §4.5 安全终态优先：no_evidence 不被聚合渲染覆盖
    assert result[2] == "no_evidence"


def test_guard_disabled_or_no_spec_returns_base(monkeypatch, tmp_path):
    monkeypatch.delenv("ANGINEER_ANSWER_AGGREGATE", raising=False)
    guard = aa.make_aggregate_guard(None, llm=object(), question="q",
                                    enabled_for_query=True, evidence_context=CONTEXT)
    assert guard([AgentMessage(role="assistant", content="draft")]) is None

    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE", "1")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(tmp_path / "absent.json"))
    aa._SPEC_CACHE.clear()
    guard2 = aa.make_aggregate_guard(None, llm=object(), question="q",
                                     enabled_for_query=True, evidence_context=CONTEXT)
    assert guard2([AgentMessage(role="assistant", content="draft")]) is None


def test_guard_render_failure_keeps_base(monkeypatch, tmp_path):
    spec_file = tmp_path / "specs.json"
    spec_file.write_text(json.dumps({"specs": [SPEC016]}), encoding="utf-8")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE", "1")
    monkeypatch.setenv("ANGINEER_ANSWER_AGGREGATE_SPECS", str(spec_file))
    monkeypatch.setattr(aa, "aggregate_answer", lambda *a, **k: None)
    aa._SPEC_CACHE.clear()
    guard = aa.make_aggregate_guard(None, llm=object(), question=Q016,
                                    enabled_for_query=True, evidence_context=CONTEXT)
    assert guard([AgentMessage(role="assistant", content="draft")]) is None


# --- 二次加深（归类失败信号） ---


def test_split_preread_index():
    idx = json.dumps({"library": "lab-firm-full", "doc_ids": {"1006-00001": "doc-a"}},
                     ensure_ascii=False, separators=(",", ":"))
    ctx = CONTEXT + "\nPREREAD INDEX (system): " + idx
    cleaned, index = aa._split_preread_index(ctx)
    assert index and index["library"] == "lab-firm-full"
    assert index["doc_ids"] == {"1006-00001": "doc-a"}
    assert "PREREAD INDEX" not in cleaned
    # 无索引行 / 坏 JSON：原样返回
    c2, i2 = aa._split_preread_index(CONTEXT)
    assert i2 is None and c2 == CONTEXT
    c3, i3 = aa._split_preread_index(CONTEXT + "\nPREREAD INDEX (system): {bad json")
    assert i3 is None


def test_deepen_reclassify_upgrades_backstop(monkeypatch):
    result = {"classifications": {
        "1010-00001": {"matter_id": "1010-00001", "values": ["unknown", "unknown"], "quote": "",
                       "finding": "", "backstop": True, "reason": "未归类兜底", "document": "arbor.docx"},
        "1006-00001": {"matter_id": "1006-00001", "values": ["2021", "always_on"], "quote": "x",
                       "finding": "", "backstop": False, "document": "d"},
    }}
    deep_text = ("Arbor Health Tech signed a 2024 credit agreement carrying always-on financial "
                 "maintenance covenants tested quarterly.")
    monkeypatch.setattr(aa, "_deep_read_blocks",
                        lambda library_id, doc_map, mids, query: {
                            "1010-00001": {"title": "arbor.docx", "text": deep_text}})
    raw2 = ("C || 1010-00001 || 2024 || always_on || "
            "signed a 2024 credit agreement carrying always-on financial || Arbor is always-on\n")
    captured = {}

    def fake_chat(llm, messages, **kwargs):
        captured["content"] = messages[0]["content"]

        class R:
            text = raw2
        return R()

    monkeypatch.setattr(aa, "_chat", fake_chat)
    index = {"library": "lab-firm-full", "doc_ids": {"1010-00001": "doc-arbor"}}
    upgraded = aa._deepen_reclassify(object(), question="maintenance covenant share", spec=SPEC016,
                                     result=result, index=index, config_name=None, mode="instruct")
    assert upgraded == 1
    row = result["classifications"]["1010-00001"]
    assert row["values"] == ["2024", "always_on"] and not row["backstop"]
    assert "Deep re-read evidence" in captured["content"]
    # 仍失败的 matter 保持兜底并更新理由
    result2 = {"classifications": {
        "1010-00001": {"matter_id": "1010-00001", "values": ["unknown", "unknown"], "quote": "",
                       "finding": "", "backstop": True, "reason": "未归类兜底", "document": "d"}}}
    monkeypatch.setattr(aa, "_deep_read_blocks",
                        lambda library_id, doc_map, mids, query: {
                            "1010-00001": {"title": "t", "text": "no usable covenant fact here " * 30}})
    monkeypatch.setattr(aa, "_chat",
                        lambda llm, messages, **k: type("R", (), {"text": "N || 1010-00001 || still unclear"})())
    upgraded2 = aa._deepen_reclassify(object(), question="q", spec=SPEC016, result=result2,
                                      index=index, config_name=None, mode="instruct")
    assert upgraded2 == 0
    assert result2["classifications"]["1010-00001"]["reason"] == "加深重读后仍不可归类"


def test_deepen_disabled_without_flag_or_index(monkeypatch):
    called = {"n": 0}

    def fake_chat(*a, **k):
        called["n"] += 1
        raise AssertionError("should not call LLM")

    monkeypatch.setattr(aa, "_chat", fake_chat)
    result = {"classifications": {
        "1010-00001": {"matter_id": "1010-00001", "values": ["unknown", "unknown"], "quote": "",
                       "finding": "", "backstop": True, "reason": "r", "document": "d"}}}
    # SPEC041 无 deepen 标记
    assert aa._deepen_reclassify(object(), question="q", spec=SPEC041, result=result,
                                 index={"library": "l", "doc_ids": {}}, config_name=None, mode="m") == 0
    # index 为 None
    assert aa._deepen_reclassify(object(), question="q", spec=SPEC016, result=result,
                                 index=None, config_name=None, mode="m") == 0
    # 目标 matter 无 doc 映射
    assert aa._deepen_reclassify(object(), question="q", spec=SPEC016, result=result,
                                 index={"library": "l", "doc_ids": {}}, config_name=None, mode="m") == 0
    assert called["n"] == 0
