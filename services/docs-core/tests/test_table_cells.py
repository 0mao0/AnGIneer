from docs_core.step04_structure.shared.table_cells import parse_table_grid
from docs_core.step04_structure.shared.table_cells import (
    estimate_col_bands,
    estimate_row_bands,
)
from docs_core.step04_structure.shared.table_cells import (
    _assign_rows_to_regions,
    _horizontal_overlap,
    _normalize_regions,
)
from docs_core.step04_structure.shared.table_cells import build_table_cells
from docs_core.step04_structure.shared.table_cells import (
    enrich_graph_nodes_table_cells,
)


def test_parse_basic_grid() -> None:
    grid = parse_table_grid("<table><tr><td>a</td><td>b</td></tr>"
                            "<tr><td>c</td><td>d</td></tr></table>")
    assert grid["rows_count"] == 2
    assert grid["cols_count"] == 2
    assert grid["cells"] == [
        {"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "a"},
        {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "b"},
        {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": "c"},
        {"row": 1, "col": 1, "rowspan": 1, "colspan": 1, "text": "d"},
    ]


def test_parse_colspan_and_rowspan() -> None:
    grid = parse_table_grid(
        "<table><tr><td rowspan=\"2\">x</td><td>a</td></tr>"
        "<tr><td colspan=\"2\">b</td></tr></table>"
    )
    # 第 0 行：x 占 (0,0) 且 rowspan=2；a 在 (0,1)
    # 第 1 行：col0 被 x 的 rowspan 占用，b 从 col1 起、colspan=2
    assert grid["cols_count"] == 3
    assert grid["cells"] == [
        {"row": 0, "col": 0, "rowspan": 2, "colspan": 1, "text": "x"},
        {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "a"},
        {"row": 1, "col": 1, "rowspan": 1, "colspan": 2, "text": "b"},
    ]


def test_parse_empty_html() -> None:
    grid = parse_table_grid("")
    assert grid == {"cells": [], "rows_count": 0, "cols_count": 0}


def test_row_bands_uniform_when_no_text() -> None:
    cells = [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": ""},
             {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": ""}]
    bands = estimate_row_bands([0.0, 0.0, 1.0, 1.0], cells, 2)
    assert bands == [(0.0, 0.5), (0.5, 1.0)]


def test_row_bands_weighted_by_text_length() -> None:
    cells = [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "x"},
             {"row": 1, "col": 0, "rowspan": 1, "colspan": 1, "text": "yyyy"}]
    bands = estimate_row_bands([0.0, 0.0, 1.0, 1.0], cells, 2)
    assert bands == [(0.0, 0.2), (0.2, 1.0)]


def test_col_bands_weighted_by_text_length() -> None:
    cells = [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1, "text": "xx"},
             {"row": 0, "col": 1, "rowspan": 1, "colspan": 1, "text": "yyy"}]
    bands = estimate_col_bands([0.0, 0.0, 1.0, 1.0], cells, 2)
    assert bands == [(0.0, 0.4), (0.4, 1.0)]


def test_normalize_regions_from_page_bboxes() -> None:
    regions = _normalize_regions([
        {"page_idx": 2, "bbox": [0.0, 0.1, 1.0, 0.5]},
        {"page_idx": 3, "bbox": [0.0, 0.0, 1.0, 0.6]},
    ])
    assert regions == [
        {"page_idx": 2, "bbox": [0.0, 0.1, 1.0, 0.5]},
        {"page_idx": 3, "bbox": [0.0, 0.0, 1.0, 0.6]},
    ]


def test_assign_rows_by_region_height() -> None:
    regions = [
        {"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 0.5]},
        {"page_idx": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
    ]
    assignment = _assign_rows_to_regions(3, regions)
    assert assignment == [0, 1, 1]


def test_horizontal_overlap() -> None:
    assert _horizontal_overlap([0.1, 0.0, 0.9, 1.0], [0.2, 0.0, 0.8, 1.0]) is True
    assert _horizontal_overlap([0.1, 0.0, 0.3, 1.0], [0.5, 0.0, 0.9, 1.0]) is False


def test_build_cells_single_region_merged() -> None:
    html = "<table><tr><td colspan=\"2\">xy</td></tr>"
    html += "<tr><td>y</td><td>z</td></tr></table>"
    cells = build_table_cells(html, [0.0, 0.0, 1.0, 1.0], page_idx=0)
    assert cells == [
        {"row": 0, "col": 0, "rowspan": 1, "colspan": 2,
         "page_idx": 0, "bbox": [0.0, 0.0, 1.0, 0.5], "text": "xy"},
        {"row": 1, "col": 0, "rowspan": 1, "colspan": 1,
         "page_idx": 0, "bbox": [0.0, 0.5, 0.5, 1.0], "text": "y"},
        {"row": 1, "col": 1, "rowspan": 1, "colspan": 1,
         "page_idx": 0, "bbox": [0.5, 0.5, 1.0, 1.0], "text": "z"},
    ]


def test_build_cells_rowspan_visual_column() -> None:
    html = "<table><tr><td rowspan=\"2\">xx</td><td>a</td></tr>"
    html += "<tr><td>b</td></tr></table>"
    cells = build_table_cells(html, [0.0, 0.0, 1.0, 1.0], page_idx=0)
    by_text = {c["text"]: c for c in cells}
    assert by_text["b"]["col"] == 1  # col0 被 rowspan 占用
    assert by_text["xx"]["bbox"] == [0.0, 0.0, 0.5, 1.0]


def test_build_cells_cross_page_by_regions() -> None:
    html = "<table><tr><td>a</td></tr><tr><td>b</td></tr></table>"
    regions = [
        {"page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0]},
        {"page_idx": 1, "bbox": [0.0, 0.0, 1.0, 1.0]},
    ]
    cells = build_table_cells(html, [0.0, 0.0, 1.0, 1.0], page_idx=0, regions=regions)
    assert cells[0]["page_idx"] == 0
    assert cells[1]["page_idx"] == 1


def _table_node(uid, html="", page_idx=0, bbox=None):
    return {
        "block_uid": uid,
        "id": uid,
        "block_type": "table",
        "page_idx": page_idx,
        "block_seq": 1,
        "table_html": html,
        "bbox": bbox or [0.0, 0.0, 1.0, 1.0],
    }


def test_enrich_writes_table_cells() -> None:
    nodes = [
        _table_node("d:0:1", "<table><tr><td>a</td></tr></table>"),
        {"block_uid": "d:0:2", "id": "d:0:2", "block_type": "paragraph",
         "page_idx": 0, "block_seq": 2, "plain_text": "text"},
    ]
    updated, stats = enrich_graph_nodes_table_cells(nodes)
    assert stats == {"total_tables": 1, "enriched": 1, "skipped": 0}
    assert updated[0]["table_cells_source"] == "estimated"
    assert updated[0]["table_cells"][0]["text"] == "a"
    assert "table_cells" not in updated[1]


def test_enrich_skips_empty_table() -> None:
    nodes = [_table_node("d:0:1", "", page_idx=0)]
    updated, stats = enrich_graph_nodes_table_cells(nodes)
    assert stats == {"total_tables": 1, "enriched": 0, "skipped": 1}
    assert "table_cells" not in updated[0]


def test_enrich_cross_page_shell_matching() -> None:
    html = "<table><tr><td>a</td></tr><tr><td>b</td></tr></table>"
    nodes = [
        _table_node("d:0:1", html, page_idx=0, bbox=[0.0, 0.0, 1.0, 1.0]),
        _table_node("d:1:1", "", page_idx=1, bbox=[0.0, 0.0, 1.0, 1.0]),
    ]
    updated, stats = enrich_graph_nodes_table_cells(nodes)
    assert stats == {"total_tables": 2, "enriched": 1, "skipped": 1}
    page_idxes = {c["text"]: c["page_idx"] for c in updated[0]["table_cells"]}
    assert page_idxes == {"a": 0, "b": 1}


def test_adapt_graph_node_carries_table_cells() -> None:
    from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import adapt_graph_node

    raw = {
        "block_uid": "d:0:1",
        "id": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "table_html": "<table><tr><td>a</td></tr></table>",
        "table_cells": [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1,
                        "page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0], "text": "a"}],
        "table_cells_source": "estimated",
    }
    adapted = adapt_graph_node(raw, 0, "")
    assert adapted["table_cells"] == raw["table_cells"]
    assert adapted["table_cells_source"] == "estimated"


def test_graph_editor_invalidates_table_cells_on_html_change() -> None:
    from docs_core.step05_sqlite_fts.graph_editor import _invalidate_edited_table_semantics

    node = {
        "block_uid": "d:0:1",
        "id": "d:0:1",
        "block_type": "table",
        "page_idx": 0,
        "block_seq": 1,
        "table_html": "<table><tr><td>a</td></tr></table>",
        "table_cells": [{"row": 0, "col": 0, "rowspan": 1, "colspan": 1,
                        "page_idx": 0, "bbox": [0.0, 0.0, 1.0, 1.0], "text": "a"}],
        "table_cells_source": "estimated",
    }
    before = {"nodes": [dict(node)]}
    after = {"nodes": [dict(node)]}
    after["nodes"][0]["table_html_corrected"] = "<table><tr><td>b</td></tr></table>"

    invalidated = _invalidate_edited_table_semantics(after, before)
    assert invalidated == ["d:0:1"]
    assert "table_cells" not in after["nodes"][0]
    assert "table_cells_source" not in after["nodes"][0]
