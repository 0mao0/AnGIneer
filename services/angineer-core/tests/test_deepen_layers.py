"""三层加深（枚举检索第二刀）：词源扩展、matter 多文档、head 兜底、预算帽与短-circuit。"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "services" / "angineer-core" / "src"))

from angineer_core import aggregate_answer as aa  # noqa: E402

SPEC = {
    "match": "maintenance covenant",
    "dims": [
        {"name": "year", "kind": "free", "pattern": "^(?:19|20)\\d{2}$", "fallback_value": "unknown"},
        {"name": "covenant", "kind": "enum",
         "buckets": ["always_on", "springing", "out_of_population", "unknown"],
         "fallback_value": "unknown"},
    ],
    "group_by": ["year"],
}


def _backstop_result(mids):
    return {"classifications": {
        mid: {"matter_id": mid, "values": ["unknown", "unknown"], "quote": "", "finding": "",
              "backstop": True, "reason": "未归类兜底", "document": "d.doc"}
        for mid in mids
    }}


def _index(primary_by_mid):
    return {"library": "lab-firm-full",
            "doc_ids": {mid: [d, d + "-alt"] for mid, d in primary_by_mid.items()},
            "cites": {mid: f"K{i + 1}" for i, mid in enumerate(primary_by_mid)}}


def test_deepen_word_source_from_question_and_buckets():
    ws = aa._deepen_word_source(
        "track how the share of our maintenance covenant springing covenants has moved",
        SPEC)
    # 题面全词（不只前 10）与 bucket 拆词都在
    for w in ("track", "maintenance", "covenant", "springing", "always", "population"):
        assert w in ws
    # 语料侧词组不入词源（零金标边界）
    assert "tested" not in ws and "quarterly" not in ws


def test_deepen_layers_shortcircuit(monkeypatch):
    mids = ["1006-00001", "1008-00001", "1010-00001"]
    result = _backstop_result(mids)
    calls = []

    def fake_layer_read(library_id, jobs, query, mode, chars):
        calls.append((mode, chars, [mid for mid, _, _ in jobs]))
        query_l = query.lower()
        # L1（match,4000）只命中 m1；L2（match,2000）命中 m2；L3（head,4000）命中 m3
        hit = {"match": {"1006-00001": 4000}, "head": {"1010-00001": 4000}}
        if mode == "match" and chars == 2000:
            return {"1008-00001": {"title": "t", "text": "springing covenant tested by board " * 20}}
        target = hit.get(mode, {}).get(chars and "" or "", "")
        # 简化：按 chars 区分 L1/L3
        if mode == "match" and chars == 4000:
            return {"1006-00001": {"title": "t", "text": "primary excerpt content here " * 50}}
        if mode == "head" and chars == 4000:
            return {"1010-00001": {"title": "t", "text": "tail doc excerpt " * 50}}
        return {}

    monkeypatch.setattr(aa, "_layer_read", fake_layer_read)
    monkeypatch.setattr(aa, "_matter_docs",
                        lambda library_id, mid, limit: [
                            {"doc_id": f"d{mid}-{i}", "title": f"t{i}"} for i in range(limit)])
    def fake_reclassify(llm, **k):
        # 与真实 _reclassify_batches 同契约：升级 = 把兜底行改为有效归类
        n = 0
        for mid in k["targets"]:
            row = k["result"]["classifications"].get(mid)
            if row and row.get("backstop"):
                row["backstop"] = False
                row["values"] = ["2021", "always_on"]
                n += 1
        return n

    monkeypatch.setattr(aa, "_reclassify_batches", fake_reclassify)

    upgraded = aa._deepen_reclassify(
        object(), question="maintenance covenant springing share", spec=SPEC,
        result=result, index=_index({mid: f"d-{mid}" for mid in mids}),
        config_name=None, mode="instruct")
    assert upgraded == 3
    # 三层依序触发；L1 只升级 m1 → L2 目标不含 m1
    assert calls[0][:2] == ("match", 4000)
    assert calls[1][:2] == ("match", 2000)
    assert calls[2][:2] == ("head", 4000)
    assert "1006-00001" not in calls[1][2]
    for mid in mids:
        assert not result["classifications"][mid]["backstop"]


def test_deepen_budget_cap_stops_layers(monkeypatch):
    mids = ["1006-00001", "1008-00001"]
    result = _backstop_result(mids)
    calls = []

    def fake_layer_read(library_id, jobs, query, mode, chars):
        calls.append(mode)
        return {mid: {"title": "t", "text": "x" * 5000} for mid, _, _ in jobs}

    monkeypatch.setattr(aa, "_layer_read", fake_layer_read)
    monkeypatch.setattr(aa, "_matter_docs",
                        lambda library_id, mid, limit: [
                            {"doc_id": f"d{mid}-{i}", "title": "t"} for i in range(limit)])
    monkeypatch.setattr(aa, "_reclassify_batches", lambda llm, **k: 0)  # 永不升级
    monkeypatch.setattr(aa, "_DEEPEN_TOTAL_BUDGET", 100)

    upgraded = aa._deepen_reclassify(
        object(), question="q", spec=SPEC, result=result,
        index=_index({mid: f"d-{mid}" for mid in mids}), config_name=None, mode="instruct")
    assert upgraded == 0
    assert calls == ["match"]  # 预算耗尽，L2/L3 不触发
    for mid in mids:
        row = result["classifications"][mid]
        assert row["backstop"] and "预算" in row["reason"]


def test_deepen_word_source_capped_at_24(monkeypatch):
    question = " ".join(f"word{i}" for i in range(40))
    ws = aa._deepen_word_source(question, SPEC)
    assert len(ws.split()) <= 24
