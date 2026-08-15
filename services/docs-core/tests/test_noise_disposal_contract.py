"""块映射契约：raw_type / block_type 归一化（05 重建侧）。"""

from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (
    build_canonical_blocks_from_source,
)


def _raw_blocks():
    return [
        {"block_uid": "b1", "block_type": "title", "plain_text": "第一章 总则", "raw_type": "title"},
        {"block_uid": "b2", "block_type": "text", "plain_text": "正文", "raw_type": "text"},
        {"block_uid": "b3", "block_type": "equation_interline", "plain_text": "F = ma", "raw_type": "equation_interline"},
        {"block_uid": "b4", "block_type": "table", "plain_text": "参数 | 数值", "raw_type": "table"},
    ]


def test_block_type_normalized_with_raw_type_kept() -> None:
    blocks = build_canonical_blocks_from_source("doc-1", _raw_blocks())
    by_id = {block.block_id: block for block in blocks}
    assert by_id["b1"].block_type == "title"
    assert by_id["b2"].block_type == "paragraph"
    assert by_id["b3"].block_type == "formula"
    assert by_id["b4"].block_type == "table"
    assert all(block.raw_type is not None for block in blocks)


def test_formula_semantics_and_table_html_carried() -> None:
    contract = {
        "formula_text": "F = ma", "formula_body": "F = ma", "formula_number": None, "formula_params": [],
        "formula_param_count": 0, "formula_summary": "F = ma",
        "llm_status": "disabled", "explanation_lines": [],
    }
    raw = [
        {
            "block_uid": "f1", "block_type": "equation_interline",
            "plain_text": "F = ma", "formula_semantics": contract,
        },
        {
            "block_uid": "t1", "block_type": "table", "plain_text": "参数",
            "table_html": "<table><tr><td>参数</td></tr></table>",
        },
    ]
    blocks = build_canonical_blocks_from_source("doc-1", raw)
    by_id = {block.block_id: block for block in blocks}
    assert by_id["f1"].formula_semantics == contract
    assert by_id["t1"].table_html and "<table" in by_id["t1"].table_html
