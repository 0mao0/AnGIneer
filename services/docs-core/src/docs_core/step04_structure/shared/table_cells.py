"""表格单元格级坐标估算（step04/shared）。"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple


TABLE_CELLS_SOURCE = "estimated"


def clean_cell_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _GridParser(HTMLParser):
    """把 <table> 解析为带 rowspan/colspan 的网格单元格。"""

    def __init__(self) -> None:
        super().__init__()
        self.cells: List[Dict[str, Any]] = []
        self.rows_count = 0
        self.cols_count = 0
        self._row: Optional[int] = None
        self._col: Optional[int] = None
        self._rowspan = 1
        self._colspan = 1
        self._parts: Optional[List[str]] = None
        self._occupied: Dict[Tuple[int, int], bool] = {}

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag == "tr":
            self._row = self.rows_count
            self.rows_count += 1
            return
        if tag in {"td", "th"} and self._row is not None:
            attr = dict(attrs)
            try:
                self._rowspan = max(1, int(attr.get("rowspan", "1") or "1"))
            except (TypeError, ValueError):
                self._rowspan = 1
            try:
                self._colspan = max(1, int(attr.get("colspan", "1") or "1"))
            except (TypeError, ValueError):
                self._colspan = 1
            col = 0
            while (self._row, col) in self._occupied:
                col += 1
            self._col = col
            self._parts = []
            for r in range(self._row, self._row + self._rowspan):
                for c in range(col, col + self._colspan):
                    self._occupied[(r, c)] = True
                    self.cols_count = max(self.cols_count, c + 1)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._parts is not None and self._row is not None:
            self.cells.append({
                "row": self._row,
                "col": self._col,
                "rowspan": self._rowspan,
                "colspan": self._colspan,
                "text": clean_cell_text("".join(self._parts)),
            })
            self._parts = None
            self._col = None

    def handle_data(self, data: str) -> None:
        if self._parts is not None:
            self._parts.append(data)


def parse_table_grid(table_html: str) -> Dict[str, Any]:
    parser = _GridParser()
    parser.feed(table_html or "")
    return {
        "cells": parser.cells,
        "rows_count": parser.rows_count,
        "cols_count": parser.cols_count,
    }
