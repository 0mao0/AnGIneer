"""Phase 6：PoPo/Solo 块对齐器 fixture 单测（海港1/海港2 真实数据 + 篡改降级）。"""

import json
from pathlib import Path

import pytest

from docs_core.step04_structure.popo.popo_signal_aligner import (
    align_document,
    align_popo_blocks,
    replay_popo_filter,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
KB = REPO_ROOT / "data" / "knowledge_base" / "libraries" / "default" / "documents"

HAIGANG1 = "doc-12f45ca9"
HAIGANG2 = "doc-c8be9f8b"


def _doc_paths(doc_id: str):
    parsed = KB / doc_id / "parsed"
    return parsed / "mineru_raw" / "middle.json", parsed / "popo" / "enriched_blocks.json"


@pytest.mark.skipif(not (KB / HAIGANG1 / "parsed").exists(), reason="真实数据目录缺失")
def test_haigang1_full_alignment() -> None:
    """海港1：middle 34 块全保留，enriched 34 块全对齐，零降级。"""
    result = align_document(HAIGANG1, *_doc_paths(HAIGANG1))
    assert not result.degraded, result.reasons
    assert len(result.pairs) == 34
    assert all(pair["passed"] for pair in result.pairs)
    assert len(result.mapping) == 34
    assert result.solo_block_uid_map["doc-12f45ca9:0"] == "doc-12f45ca9:0:1"


@pytest.mark.skipif(not (KB / HAIGANG2 / "parsed").exists(), reason="真实数据目录缺失")
def test_haigang2_identifies_four_skipped_blocks() -> None:
    """海港2：middle 169 → 幸存 165，正确识别 4 个被跳过块（3 空 index + 1 空 chart）。"""
    middle_path, enriched_path = _doc_paths(HAIGANG2)
    middle = json.loads(middle_path.read_text(encoding="utf-8"))
    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    survivors, skipped = replay_popo_filter(middle)
    assert len(survivors) == 165
    assert len(skipped) == 4
    assert all(item["reason"] == "empty" for item in skipped)
    assert [item["type"] for item in skipped].count("index") == 3
    assert any(item["type"] == "chart" for item in skipped)

    result = align_popo_blocks(HAIGANG2, middle, enriched)
    assert not result.degraded, result.reasons
    assert len(result.pairs) == 165
    assert len(result.mapping) == 165


@pytest.mark.skipif(not (KB / HAIGANG2 / "parsed").exists(), reason="真实数据目录缺失")
def test_haigang2_contd_pair_both_ends_aligned() -> None:
    """海港2：contd 标记对（id 115→116）两端 source_id 均对齐到 solo 块。"""
    middle_path, enriched_path = _doc_paths(HAIGANG2)
    middle = json.loads(middle_path.read_text(encoding="utf-8"))
    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))
    result = align_popo_blocks(HAIGANG2, middle, enriched)

    by_id = {int(block.get("id", -1)): block for block in enriched}
    source_blocks = [block for block in enriched if int(block.get("contd", -1)) >= 0]
    assert source_blocks, "海港2 必须存在 contd 续接标记"
    for block in source_blocks:
        source_id = str(block.get("source_id") or "")
        target_id = int(block.get("contd"))
        target_block = by_id.get(target_id)
        assert target_block is not None
        target_source_id = str(target_block.get("source_id") or "")
        assert source_id in result.solo_block_uid_map
        assert target_source_id in result.solo_block_uid_map


def test_tampered_enriched_reports_degraded() -> None:
    """被篡改的 enriched json（删块/乱序）→ 正确报降级。"""
    middle_path, enriched_path = _doc_paths(HAIGANG1)
    if not middle_path.exists():
        pytest.skip("真实数据目录缺失")
    middle = json.loads(middle_path.read_text(encoding="utf-8"))
    enriched = json.loads(enriched_path.read_text(encoding="utf-8"))

    deleted = enriched[1:]
    result = align_popo_blocks(HAIGANG1, middle, deleted)
    assert result.degraded
    assert any("块数不一致" in reason for reason in result.reasons)

    reordered = [enriched[0], *enriched[2:], enriched[1]]
    result = align_popo_blocks(HAIGANG1, middle, reordered)
    assert result.degraded
    assert any("校验失败" in reason for reason in result.reasons)


def test_extract_block_content_extracts_nested_table_html() -> None:
    """middle.json 表格内容嵌套在 blocks[].lines[].spans[].html，extract_block_content 应提取。"""
    from popo.post_processing.label_normalization import extract_block_content

    block = {
        "type": "table",
        "bbox": [0, 0, 100, 100],
        "blocks": [
            {"type": "table_caption", "lines": [{"spans": [{"content": "表1"}]}]},
            {
                "type": "table_body",
                "lines": [{
                    "spans": [{
                        "type": "table",
                        "html": "<table><tr><td>a</td><td>b</td></tr></table>",
                    }]
                }],
            },
        ],
    }
    content = extract_block_content(block)
    assert "<tr>" in content
    assert "a" in content


def test_table_alignment_skips_text_compare() -> None:
    """表格内容为 HTML 时对齐只依赖 page+bbox，不做文本比对（旧 enriched 可能为空串）。"""
    middle = {
        "pdf_info": [{
            "page_idx": 0,
            "page_size": [1000, 1000],
            "para_blocks": [{
                "type": "table",
                "bbox": [0, 0, 500, 500],
                "blocks": [{
                    "type": "table_body",
                    "lines": [{"spans": [{"type": "table", "html": "<table><tr><td>x</td></tr></table>"}]}],
                }],
            }],
        }]
    }
    enriched = [{
        "source_id": "d:0",
        "page": 1,
        "bbox": [0, 0, 0.5, 0.5],
        "type": "table",
        "content": "",
    }]
    result = align_popo_blocks("d", middle, enriched)
    assert not result.degraded
    assert result.pairs[0]["passed"]

def test_replay_filter_skips_empty_and_skip_type_synthetic() -> None:
    middle = {
        "pdf_info": [
            {
                "page_idx": 0,
                "page_size": [100, 200],
                "para_blocks": [
                    {"type": "title", "content": "第一章"},
                    {"type": "index", "content": ""},
                    {"type": "discarded", "content": "噪声"},
                    {"type": "text", "content": "正文"},
                ],
            }
        ]
    }
    survivors, skipped = replay_popo_filter(middle)
    assert [item["content"] for item in survivors] == ["第一章", "正文"]
    assert len(skipped) == 2
    assert skipped[0]["reason"] == "empty"
    assert skipped[1]["reason"] == "skip_type"
