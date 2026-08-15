"""Phase 7：PoPo 续接/表格合并信号注入（Solo 执行合并 + 规则校验 + 拒绝兜底）。"""

import json
from pathlib import Path

import pytest

from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
from docs_core.step04_structure.popo.popo_signal_injector import (
    inject_popo_signals,
    validate_instruction,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
KB = REPO_ROOT / "data" / "knowledge_base" / "libraries" / "default" / "documents"
HAIGANG2 = "doc-c8be9f8b"


def _load_doc(doc_id: str):
    parsed = KB / doc_id / "parsed"
    middle = json.loads((parsed / "mineru_raw" / "middle.json").read_text(encoding="utf-8"))
    enriched = json.loads((parsed / "popo" / "enriched_blocks.json").read_text(encoding="utf-8"))
    return middle, enriched


def _solo_nodes_for(doc_id: str):
    from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles

    parsed = KB / doc_id / "parsed"
    result = build_structured_from_rawfiles(
        parsed, doc_id, doc_id, llm_client=None, options={"use_llm": False}
    )
    return result.nodes


@pytest.mark.skipif(not (KB / HAIGANG2 / "parsed").exists(), reason="真实数据目录缺失")
def test_haigang2_654_contd_pair_injected_matches_popo_jsonl() -> None:
    """海港2 6.5.4 续接对：注入后 solo 11:14 → 12:1，与落盘 jsonl 保留的标记一致。"""
    middle, enriched = _load_doc(HAIGANG2)
    nodes = _solo_nodes_for(HAIGANG2)
    alignment = align_popo_blocks(HAIGANG2, middle, enriched)
    assert not alignment.degraded

    updated, stats = inject_popo_signals(HAIGANG2, nodes, enriched, alignment)
    assert stats["applied"] >= 1

    by_uid = {node["block_uid"]: node for node in updated}
    source = by_uid["doc-c8be9f8b:11:14"]
    assert source["contd_target_id"] == "doc-c8be9f8b:12:1"
    assert source["plain_text"].startswith("6.5.4锚地应布置在")
    target = by_uid["doc-c8be9f8b:12:1"]
    assert target["plain_text"].startswith("浪和水流较小")
    # 文本不物理拼接（与 popo jsonl 一致：标记而非合并）
    assert "浪和水流较小" not in source["plain_text"]

    # 与落盘 jsonl 一致：合并 pass 已把 11:14 吸收 12:1，落盘为单节点完整段落
    saved_nodes = []
    with open(KB / HAIGANG2 / "parsed" / "doc_blocks_graph.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                saved_nodes.append(json.loads(line))
    saved_by_uid = {node["block_uid"]: node for node in saved_nodes}
    merged = saved_by_uid["doc-c8be9f8b:11:14"]
    assert "contd_target_id" not in merged
    assert merged["merged_from"] == ["doc-c8be9f8b:12:1"]
    assert [item["page_idx"] for item in (merged.get("page_bboxes") or [])] == [11, 12]
    assert merged["plain_text"].startswith("6.5.4锚地应布置在")
    assert "浪和水流较小" in merged["plain_text"]
    assert "doc-c8be9f8b:12:1" not in saved_by_uid


def test_contd_rejected_when_target_is_title() -> None:
    nodes = [
        {
            "block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0,
            "block_seq": 1, "plain_text": "续接前半",
        },
        {
            "block_uid": "d:0:2", "block_type": "title", "page_idx": 0,
            "block_seq": 2, "plain_text": "下一章",
        },
    ]
    instruction = {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:0:2"}
    ok, reason = validate_instruction({node["block_uid"]: node for node in nodes}, instruction)
    assert not ok
    assert "标题" in reason or "不兼容" in reason


def test_contd_rejected_when_crossing_title() -> None:
    nodes = [
        {"block_uid": "d:0:1", "block_type": "paragraph", "page_idx": 0, "block_seq": 1},
        {"block_uid": "d:0:2", "block_type": "title", "page_idx": 0, "block_seq": 2},
        {"block_uid": "d:0:3", "block_type": "paragraph", "page_idx": 0, "block_seq": 3},
    ]
    instruction = {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:0:3"}
    ok, reason = validate_instruction({node["block_uid"]: node for node in nodes}, instruction)
    assert not ok
    assert "跨越标题" in reason


def test_table_merge_valid_when_columns_match() -> None:
    html = "<table><tr><td>a</td><td>b</td></tr></table>"
    nodes = [
        {
            "block_uid": "d:0:1", "block_type": "table", "page_idx": 0,
            "block_seq": 1, "table_html": html,
        },
        {
            "block_uid": "d:1:1", "block_type": "table", "page_idx": 1,
            "block_seq": 2, "table_html": html,
        },
    ]
    instruction = {"kind": "table_merge", "source_uid": "d:0:1", "target_uid": "d:1:1"}
    ok, reason = validate_instruction({node["block_uid"]: node for node in nodes}, instruction)
    assert ok, reason


def test_table_merge_rejected_when_columns_differ() -> None:
    nodes = [
        {
            "block_uid": "d:0:1", "block_type": "table", "page_idx": 0,
            "block_seq": 1, "table_html": "<table><tr><td>a</td><td>b</td></tr></table>",
        },
        {
            "block_uid": "d:1:1", "block_type": "table", "page_idx": 1,
            "block_seq": 2, "table_html": "<table><tr><td>a</td></tr></table>",
        },
    ]
    instruction = {"kind": "table_merge", "source_uid": "d:0:1", "target_uid": "d:1:1"}
    ok, reason = validate_instruction({node["block_uid"]: node for node in nodes}, instruction)
    assert not ok
    assert "列数不一致" in reason


def test_degraded_alignment_skips_injection() -> None:
    """对齐降级时节点原样返回（与无 PoPo 信号一致）。"""
    nodes = [{"block_uid": "d:0:1", "block_type": "paragraph", "plain_text": "正文"}]
    alignment = align_popo_blocks(
        "d",
        {"pdf_info": [{"page_idx": 0, "para_blocks": [{"type": "text", "content": "A"}]}]},
        [],  # enriched 缺失 → 块数不一致 → 降级
    )
    assert alignment.degraded
    updated, stats = inject_popo_signals("d", nodes, [], alignment)
    assert updated == nodes
    assert stats["skipped_reason"] == "alignment_degraded"


def test_apply_signals_wiring_skips_when_no_popo(monkeypatch, tmp_path) -> None:
    """solo2json_pipeline._apply_popo_signals：无 popo 产物时原样返回。"""
    import docs_core.docs_file_io as afs
    from docs_core.step04_structure import solo2json_pipeline

    class _FS:
        def read_popo_enriched_blocks(self, library_id, doc_id):
            raise FileNotFoundError("no popo")

    monkeypatch.setattr(afs, "file_storage", _FS())
    nodes = [{"block_uid": "d:0:1", "block_type": "paragraph", "plain_text": "正文"}]
    updated, stats, popo_candidates = solo2json_pipeline._apply_popo_signals(
        "lib", "doc", nodes
    )
    assert updated == nodes
    assert stats["injection"]["skipped_reason"] == "no_popo"
    assert "level_fusion" not in stats
    assert popo_candidates == {}
