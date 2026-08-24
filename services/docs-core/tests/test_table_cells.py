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
