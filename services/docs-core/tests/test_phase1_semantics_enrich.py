"""阶段一契约测试：语义层 Canonical 入口（表格四分类 + 公式契约）。"""

from docs_core.read.normalize.popo.popo_mapper import po_po_blocks_to_canonical
from docs_core.read.organize.builder import build_canonical_document_from_popoblocks
from docs_core.read.organize.types import CanonicalBlock, CanonicalTable
from docs_core.read.normalize.semantics.formula_semantics import (
    collect_canonical_explanation_lines,
    enrich_canonical_block,
)
from docs_core.read.normalize.semantics.table_semantics import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
    enrich_canonical_table,
)
from fixtures.popo_fixtures import EMPTY_TREE, build_clean_fixture


def test_enrich_canonical_table_contract() -> None:
    table = CanonicalTable(
        table_id="t1",
        doc_id="d",
        title="构件参数表",
        header_rows=[["参数", "数值"]],
        body_rows=[["高度", "100"], ["宽度", "200"]],
    )
    enriched = enrich_canonical_table(table)
    assert set(enriched) == {"table_type", "summary", "row_keys", "text_chunks"}
    assert enriched["table_type"] in {
        TABLE_TYPE_HYBRID,
        TABLE_TYPE_MAPPING_ENUM,
        TABLE_TYPE_NUMERIC_DENSE,
        TABLE_TYPE_TEXT_DENSE,
    }
    assert enriched["summary"]
    assert enriched["row_keys"] == ["高度", "宽度"]
    assert enriched["text_chunks"]


def test_enrich_canonical_block_contract() -> None:
    formula = CanonicalBlock(
        block_id="f1", doc_id="d", page_idx=2, reading_order=10,
        block_type="formula", text="N = μ·F", section_path="5.1",
    )
    explain = CanonicalBlock(
        block_id="p1", doc_id="d", page_idx=2, reading_order=11,
        block_type="paragraph", text="式中：μ 为摩擦系数；F 为法向力。", section_path="5.1",
    )
    distant = CanonicalBlock(
        block_id="p2", doc_id="d", page_idx=5, reading_order=12,
        block_type="paragraph", text="远处无关段落", section_path="其他章节",
    )
    contract = enrich_canonical_block(formula, [formula, explain, distant])
    assert contract["formula_text"] == "N = μ·F"
    assert contract["formula_params"], "公式参数契约必须非空"
    assert all(item["extracted_by"] == "rule" for item in contract["formula_params"])
    symbols = [item["symbol"] for item in contract["formula_params"]]
    assert "μ" in symbols and "F" in symbols
    assert contract["llm_status"] == "disabled"
    # 远处/跨章节段落不进入解释段
    assert collect_canonical_explanation_lines(formula, [explain, distant]) == [
        "式中：μ 为摩擦系数；F 为法向力。"
    ]


def test_enrich_canonical_block_skips_non_formula() -> None:
    paragraph = CanonicalBlock(block_id="p", doc_id="d", block_type="paragraph", text="正文")
    contract = enrich_canonical_block(paragraph, [paragraph])
    assert contract["formula_params"] == []
    assert contract["llm_status"] == "skipped"


def test_builder_wires_formula_semantics() -> None:
    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", build_clean_fixture(), EMPTY_TREE
    )
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
    )
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics, "公式块必须挂载语义契约"
    assert formula_block.formula_semantics["formula_params"]
    assert formula_block.formula_semantics["formula_params"][0]["extracted_by"] == "rule"


def test_rebuild_from_graph_enriches_tables_and_formulas() -> None:
    """graph 重建路径（solo 降级后端）下表格与公式语义同时生效。"""
    from docs_core.read.organize.builder import rebuild_canonical_document_from_graph

    graph = {
        "nodes": [
            {
                "block_uid": "t1", "block_type": "table", "page_idx": 0, "block_seq": 1,
                "plain_text": "参数 | 数值",
                "table_html": "<table><tr><td>参数</td><td>数值</td></tr>"
                              "<tr><td>高度</td><td>100</td></tr></table>",
                "section_path": "", "derived_level": None,
            },
            {
                "block_uid": "f1", "block_type": "formula", "page_idx": 1, "block_seq": 2,
                "plain_text": "N = μ·F", "section_path": "5.1", "derived_level": None,
            },
            {
                "block_uid": "p1", "block_type": "paragraph", "page_idx": 1, "block_seq": 3,
                "plain_text": "式中：μ 为摩擦系数；F 为法向力。",
                "section_path": "5.1", "derived_level": None,
            },
        ],
        "edges": [],
    }
    document = rebuild_canonical_document_from_graph("lib-1", "doc-1", graph, title="示例")
    assert document.tables and document.tables[0].row_count == 1
    formula_block = next(b for b in document.blocks if b.block_type == "formula")
    assert formula_block.formula_semantics
    assert formula_block.formula_semantics["formula_params"]
