from docs_core.step04_structure.shared.table_cells import parse_table_grid


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
