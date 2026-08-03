"""阶段一契约测试：popo 表格内容通道（G1）+ schema_version。"""

from docs_core.ingest.structure.popo_mapper import po_po_blocks_to_canonical
from docs_core.ingest.canonical.builder import build_canonical_document_from_popoblocks
from docs_core.ingest.canonical.types import CanonicalBlock
from docs_core.ingest.structure.popo_table_extract import (
    extract_table_html,
    parse_table_html,
    textify_table_html,
)
from fixtures.popo_fixtures import (
    EMPTY_TREE,
    MERGED_TABLE_HTML,
    build_table_fixture,
)


def test_extract_table_html_variants() -> None:
    html = "<table><tr><td>a</td></tr></table>"
    assert extract_table_html({"content": html}) == html
    assert extract_table_html({"content": {"html": html}}) == html
    assert extract_table_html({"content": {"table_html": html}}) == html
    assert extract_table_html({"content": "纯文本内容"}) is None
    assert extract_table_html(None) is None


def test_parse_table_html_respects_colspan() -> None:
    rows = parse_table_html(
        "<table><tr><th colspan=\"2\">参数</th><th>数值</th></tr>"
        "<tr><td>高度</td><td>H</td><td>100</td></tr></table>"
    )
    assert rows[0] == ["参数", "参数", "数值"]
    assert rows[1] == ["高度", "H", "100"]


def test_textify_table_html_keeps_rows() -> None:
    text = textify_table_html(MERGED_TABLE_HTML)
    assert "<table" not in text
    assert "参数 | 参数 | 数值" in text
    assert "深度 | D | 300" in text


def _map_table_fixture():
    blocks, outlines, _, pages = po_po_blocks_to_canonical(
        "doc-1", build_table_fixture(), EMPTY_TREE
    )
    return blocks, outlines, pages


def test_mapper_attaches_table_html_and_schema_version() -> None:
    blocks, _, _ = _map_table_fixture()
    table_block = next(b for b in blocks if b.block_type == "table")
    assert table_block.table_html == MERGED_TABLE_HTML
    assert table_block.raw_type == "table"
    assert table_block.schema_version == "v2"
    # HTML 不流进 block 文本（避免污染 FTS），textified 内容保留
    assert "<table" not in table_block.text
    assert "高度 | H | 100" in table_block.text


def test_popoblocks_builds_nonempty_canonical_tables(tmp_path) -> None:
    blocks, outlines, pages = _map_table_fixture()
    document = build_canonical_document_from_popoblocks(
        library_id="lib-1", doc_id="doc-1", title="",
        blocks=blocks, outlines=outlines, pages=pages,
    )
    assert document.tables, "popo 路径 canonical_tables 必须非空"
    table = document.tables[0]
    assert table.row_count == 3
    assert table.col_count == 3
    assert table.header_rows == [["参数", "参数", "数值"]]
    assert table.body_rows[0] == ["高度", "H", "100"]
    assert table.body_rows[-1] == ["深度", "D", "300"]
    # caption 行作为标题
    assert table.title == "表 5.2-1 构件尺寸参数"
    # HTML 不流入任何 chunk
    chunk_text = "\n".join(c.text for c in document.chunks)
    assert "<table" not in chunk_text
    assert "深度 | D | 300" in chunk_text


def _table_block(block_id: str, table_html: str = "") -> CanonicalBlock:
    return CanonicalBlock(
        block_id=block_id, doc_id="d", page_idx=0, reading_order=1,
        block_type="table", text="参数 | 数值", text_clean="参数 | 数值",
        section_path="", raw_type="table", table_html=table_html or None,
    )


def test_solo_path_tables_built_from_raw_blocks() -> None:
    from docs_core.ingest.canonical.builder import build_canonical_tables_from_source

    html = "<table><tr><td>参数</td><td>数值</td></tr><tr><td>高度</td><td>100</td></tr></table>"
    raw = [{
        "block_uid": "b1", "block_type": "table", "page_idx": 0, "block_seq": 1,
        "plain_text": "参数 | 数值", "table_html": html,
        "caption": "表 1 参数表", "section_path": "",
    }]
    tables, chunks = build_canonical_tables_from_source("d", raw, [_table_block("b1", html)])
    assert len(tables) == 1
    assert tables[0].row_count == 1
    assert tables[0].title == "表 1 参数表"
    assert tables[0].text_chunks
    assert chunks


def test_tables_fallback_to_canonical_table_html_when_graph_lacks_html() -> None:
    """popo 断链场景：graph 节点无 table_html 时回退 CanonicalBlock 旁路字段。"""
    from docs_core.ingest.canonical.builder import build_canonical_tables_from_source

    html = "<table><tr><td>参数</td><td>数值</td></tr><tr><td>高度</td><td>100</td></tr></table>"
    raw = [{
        "block_uid": "b1", "block_type": "table", "page_idx": 0, "block_seq": 1,
        "plain_text": "参数 | 数值", "section_path": "",
    }]
    tables, _ = build_canonical_tables_from_source("d", raw, [_table_block("b1", html)])
    assert len(tables) == 1
    assert tables[0].row_count == 1
    assert tables[0].header_rows == [["参数", "数值"]]
