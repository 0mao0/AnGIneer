import json
from pathlib import Path

import pytest

from docs_core.step04_structure.shared.title_level_resolver import (
    DEFAULT_CONFIDENCE_THRESHOLD, resolve_title_levels,
)


def _title(uid, text, level, conf=0.5, part="body", role="body"):
    return {
        "block_uid": uid, "block_type": "title", "plain_text": text,
        "derived_level": level, "title_level": level, "confidence": conf,
        "derived_by": "rule", "document_part": part, "page_role": role,
    }


class _LLM:
    def __init__(self, items, captured=None):
        self.items = items
        self.captured = captured if captured is not None else []

    def chat(self, messages, temperature=0.0, model=None):
        prompt = json.loads(messages[-1]["content"])
        self.captured.append(prompt["items"])
        return json.dumps({"items": self.items})


def test_front_matter_titles_are_skipped_by_arbitration():
    nodes = [_title("d:3:1", "修订说明", 1, conf=0.7, part="front_matter", role="revision_notes")]
    llm = _LLM([])
    updated, stats = resolve_title_levels(
        nodes, popo_levels={"d:3:1": 1}, tree_levels={"d:3:1": 1},
        llm_client=llm, use_llm=True,
    )
    assert updated[0]["derived_level"] == 1
    assert llm.captured == []
    assert stats["consistent"] == 0
    assert stats["disputed"] == 0
    assert stats["total_titles"] == 0


def test_strong_disagreement_escalates_even_high_confidence():
    nodes = [_title("d:3:1", "修订说明", 2, conf=0.95)]
    llm = _LLM([{"block_id": "d:3:1", "level": 1, "confidence": 0.9}])
    updated, stats = resolve_title_levels(
        nodes, popo_levels={"d:3:1": 1}, tree_levels={"d:3:1": 1},
        llm_client=llm, use_llm=True,
    )
    assert stats["disputed"] == 1
    assert updated[0]["derived_level"] == 1
    assert updated[0]["derived_by"].endswith("+llm")


def test_weak_disagreement_high_confidence_keeps_rule():
    nodes = [_title("d:0:1", "5.1 一般规定", 2, conf=0.95)]
    llm = _LLM([])
    updated, stats = resolve_title_levels(
        nodes, popo_levels={"d:0:1": 3}, tree_levels=None,
        llm_client=llm, use_llm=True,
    )
    assert updated[0]["derived_level"] == 2
    assert llm.captured == []
    assert stats["disputed"] == 0


def test_low_confidence_dispute_sends_dual_candidate():
    nodes = [_title("d:0:1", "第一章 总则", 2, conf=0.3)]
    llm = _LLM([{"block_id": "d:0:1", "level": 1, "confidence": 0.9}], captured=[])
    updated, stats = resolve_title_levels(
        nodes, popo_levels={"d:0:1": 1}, tree_levels=None,
        llm_client=llm, use_llm=True,
    )
    assert stats["disputed"] == 1
    item = llm.captured[0][0]
    assert item["rule_level"] == 2 and item["popo_level"] == 1


def test_low_confidence_no_popo_sends_single_candidate_review():
    nodes = [_title("d:0:1", "总则", 1, conf=0.6)]
    llm = _LLM([{"block_id": "d:0:1", "level": 1, "confidence": 0.95}], captured=[])
    updated, stats = resolve_title_levels(
        nodes, popo_levels=None, tree_levels=None,
        llm_client=llm, use_llm=True,
    )
    assert stats["review"] == 1
    assert "popo_level" not in llm.captured[0][0]
    assert updated[0]["derived_level"] == 1


def test_no_llm_keeps_rule_and_status_disabled():
    nodes = [_title("d:0:1", "总则", 1, conf=0.6)]
    updated, stats = resolve_title_levels(nodes, use_llm=False)
    assert updated[0]["derived_level"] == 1
    assert stats["llm_status"] == "disabled"


REPO_ROOT = Path(__file__).resolve().parents[3]
KB = REPO_ROOT / "data" / "knowledge_base" / "libraries" / "default" / "documents"
CASES = ["doc-12f45ca9", "doc-406e43e8", "doc-c8be9f8b"]


@pytest.mark.skipif(not (KB / "doc-406e43e8" / "parsed").exists(), reason="真实数据缺失")
def test_real_docs_front_matter_levels_and_parts():
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles
    from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
    from docs_core.step04_structure.popo.popo_signal_level_fusion import (
        build_popo_level_map, build_popo_tree_level_map,
    )

    for doc in CASES:
        parsed = KB / doc / "parsed"
        nodes = build_structured_from_rawfiles(
            parsed, doc, doc, llm_client=None, options={"use_llm": False}
        ).nodes
        middle = json.loads((parsed / "mineru_raw" / "middle.json").read_text(encoding="utf-8"))
        enriched = json.loads((parsed / "popo" / "enriched_blocks.json").read_text(encoding="utf-8"))
        alignment = align_popo_blocks(doc, middle, enriched)
        assert not alignment.degraded
        popo_levels = {
            alignment.solo_block_uid_map[sid]: level
            for sid, level in build_popo_level_map(enriched, alignment).items()
            if sid in alignment.solo_block_uid_map
        }
        tree = json.loads((parsed / "popo" / "document_tree.json").read_text(encoding="utf-8"))
        tree_levels = build_popo_tree_level_map(tree, enriched, alignment)
        resolved, stats = resolve_title_levels(
            nodes, popo_levels=popo_levels, tree_levels=tree_levels, use_llm=False,
        )
        by_uid = {n["block_uid"]: n for n in resolved}
        if doc == "doc-406e43e8":
            assert by_uid["doc-406e43e8:3:1"]["derived_level"] is None   # 修订说明
            assert by_uid["doc-406e43e8:3:1"]["document_part"] == "front_matter"
            assert by_uid["doc-406e43e8:5:1"]["derived_level"] is None   # 目次
            # 正文页出现“附录 D”交叉引用不应被误判为附录
            assert by_uid["doc-406e43e8:14:4"]["document_part"] == "body"   # 4.2 容许应力
            assert by_uid["doc-406e43e8:18:8"]["document_part"] == "body"   # 5.3 连接
            # 正文标题的规则层级不依赖 popo 信号（信号可能随解析数据漂移）
            assert by_uid["doc-406e43e8:8:1"]["derived_level"] == 1   # 2 基本规定
            assert by_uid["doc-406e43e8:8:2"]["derived_level"] == 2   # 2.1 一般规定
        assert "disputed" in stats
