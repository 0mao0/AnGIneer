"""表格块渲染单测（2026-10-21）：多行表头必须压成一行、数据行必须逐行带序号。

事故背景：financebench 财务比率题的利润表是两行表头（「Fiscal Year」×3 + 「2019/2018/2017」），
原样输出后三列同名，模型把数值对错年份列；这里锁住「列义唯一 + 行边界清晰」。
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src")))

from docs_core.step09_query.agent_port import _merge_header_rows, _table_block_text  # noqa: E402


BLOCK = {
    "context": "Consolidated Statements of Earnings",
    "header_rows": [["", "Fiscal Year", "Fiscal Year", "Fiscal Year"], ["", "2019", "2018", "2017"]],
    "rows": [
        ["Net sales", "$ 16,865.2", "$ 15,740.4", "$ 15,619.8"],
        ["Cost of sales", "11,108.4", "10,304.8", "10,052.0"],
    ],
    "doc_id": "v1-8593916db41c",
    "page_idx": 41,
}


def test_merge_header_rows_builds_unique_column_names():
    merged = _merge_header_rows(BLOCK["header_rows"])
    assert merged == ["（行标签）", "Fiscal Year 2019", "Fiscal Year 2018", "Fiscal Year 2017"]


def test_table_text_has_one_header_line_and_numbered_rows():
    text = _table_block_text(BLOCK)
    lines = text.splitlines()
    assert lines[0].startswith("表格《Consolidated Statements of Earnings》")
    assert lines[1] == "列：（行标签） | Fiscal Year 2019 | Fiscal Year 2018 | Fiscal Year 2017"
    assert lines[2] == "1. Net sales | $ 16,865.2 | $ 15,740.4 | $ 15,619.8"
    assert lines[3] == "2. Cost of sales | 11,108.4 | 10,304.8 | 10,052.0"
    # 表头不得与首个数据行拼在同一行（2026-10-21 复核点）
    assert "2017 Net sales" not in text
