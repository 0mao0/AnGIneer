"""PoPo 结构层（阶段一：表格内容通道）。"""
from .popo_table_extract import (
    extract_table_html,
    parse_table_html,
    textify_table_html,
)

__all__ = [
    "extract_table_html",
    "parse_table_html",
    "textify_table_html",
]
