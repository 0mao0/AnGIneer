"""统一仲裁接线：无/有 PoPo 信号都执行；contd/table_merge 注入独立保留。"""
import json

import pytest

from docs_core.step04_structure import solo2json_pipeline


class _MockLLM:
    def __init__(self, items):
        self.items = items
        self.calls = 0

    def chat(self, messages, temperature=0.0, model=None):
        self.calls += 1
        return json.dumps({"items": self.items})


def _title_node(uid="d:0:1", text="总则", level=1, confidence=0.6, part="body", role="body"):
    return {
        "block_uid": uid, "block_type": "title", "page_idx": 0, "block_seq": 1,
        "plain_text": text, "derived_level": level, "title_level": level,
        "confidence": confidence, "document_part": part, "page_role": role,
    }


def test_resolve_runs_review_without_popo():
    nodes = [_title_node()]
    llm = _MockLLM([{"block_id": "d:0:1", "level": 1, "confidence": 0.95}])
    updated, stats = solo2json_pipeline._resolve_title_levels(
        nodes, doc_id="d", popo_candidates=None, llm_client=llm, use_llm=True,
    )
    assert stats["llm_status"] == "ok"
    assert stats["review"] == 1
    assert updated[0]["title_level"] == 1


def test_resolve_disabled_without_use_llm():
    nodes = [_title_node()]
    updated, stats = solo2json_pipeline._resolve_title_levels(
        nodes, doc_id="d", popo_candidates=None, llm_client=_MockLLM([]), use_llm=False,
    )
    assert stats["llm_status"] == "disabled"
    assert updated == nodes


def test_resolve_numbered_title_skips_llm_call():
    nodes = [_title_node(text="1 总则", confidence=0.95)]
    llm = _MockLLM([])
    updated, stats = solo2json_pipeline._resolve_title_levels(
        nodes, doc_id="d", popo_candidates=None, llm_client=llm, use_llm=True,
    )
    assert llm.calls == 0
    assert stats["llm_status"] == "skipped_by_confidence" or stats["adopt"] == 1
    assert updated[0]["title_level"] == 1
