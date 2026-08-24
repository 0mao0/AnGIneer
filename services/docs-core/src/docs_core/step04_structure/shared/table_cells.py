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


def estimate_row_bands(bbox, cells, rows_count):
    return _estimate_bands(bbox, cells, rows_count, axis="row")


def estimate_col_bands(bbox, cells, cols_count):
    return _estimate_bands(bbox, cells, cols_count, axis="col")


def _estimate_bands(bbox, cells, count, *, axis):
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    if count <= 0:
        return []
    weights = [0.0] * count
    for cell in cells:
        if axis == "row":
            start = cell["row"]
            span = cell["rowspan"]
        else:
            start = cell["col"]
            span = cell["colspan"]
        share = len(cell["text"]) / max(1, span)
        for index in range(start, min(start + span, count)):
            weights[index] += share
    total = sum(weights)
    start = y1 if axis == "row" else x1
    end = y2 if axis == "row" else x2
    if total <= 0:
        unit = (end - start) / count
        return [(start + unit * i, start + unit * (i + 1)) for i in range(count)]
    bands = []
    cursor = start
    for weight in weights:
        size = (end - start) * (weight / total)
        bands.append((cursor, cursor + size))
        cursor += size
    bands[-1] = (bands[-1][0], end)
    return bands


def _normalize_regions(regions):
    out: List[Dict[str, Any]] = []
    for item in regions or []:
        if isinstance(item, dict):
            bbox = item.get("bbox")
            page_idx = item.get("page_idx", 0)
        elif isinstance(item, (list, tuple)) and len(item) >= 4:
            bbox = item
            page_idx = 0
        else:
            continue
        if not (isinstance(bbox, (list, tuple)) and len(bbox) >= 4):
            continue
        try:
            out.append({
                "page_idx": int(page_idx),
                "bbox": [float(v) for v in bbox[:4]],
            })
        except (TypeError, ValueError):
            continue
    return out


def _assign_rows_to_regions(rows_count, regions):
    if rows_count <= 0:
        return []
    if not regions:
        return [0] * rows_count
    heights = [max(0.0, r["bbox"][3] - r["bbox"][1]) for r in regions]
    total = sum(heights) or 1.0
    boundaries = []
    acc = 0.0
    for height in heights:
        acc += height / total
        boundaries.append(acc)
    assignment = []
    for row in range(rows_count):
        frac = (row + 0.5) / rows_count
        idx = 0
        while idx < len(boundaries) - 1 and frac >= boundaries[idx]:
            idx += 1
        assignment.append(idx)
    return assignment


def _horizontal_overlap(a, b):
    return max(a[0], b[0]) < min(a[2], b[2])


def build_table_cells(table_html, bbox, *, page_idx=0, regions=None):
    grid = parse_table_grid(table_html)
    cells = grid["cells"]
    rows_count = grid["rows_count"]
    cols_count = grid["cols_count"]
    if not cells or rows_count <= 0 or cols_count <= 0:
        return []
    normalized = _normalize_regions(regions) if regions else [
        {"page_idx": int(page_idx), "bbox": [float(v) for v in bbox[:4]]},
    ]
    if not normalized:
        normalized = [{"page_idx": int(page_idx), "bbox": [float(v) for v in bbox[:4]]}]
    row_region = _assign_rows_to_regions(rows_count, normalized)
    region_rows: Dict[int, List[int]] = {}
    for row, region_idx in enumerate(row_region):
        region_rows.setdefault(region_idx, []).append(row)
    out: List[Dict[str, Any]] = []
    for region_idx, region in enumerate(normalized):
        rows = region_rows.get(region_idx, [])
        if not rows:
            continue
        region_cells = [c for c in cells if c["row"] in rows]
        rbands = estimate_row_bands(region["bbox"], region_cells, len(rows))
        cbands = estimate_col_bands(region["bbox"], region_cells, cols_count)
        local_row = {row: i for i, row in enumerate(rows)}
        for cell in region_cells:
            r0 = local_row[cell["row"]]
            r1 = min(r0 + cell["rowspan"] - 1, len(rows) - 1)
            c0 = cell["col"]
            c1 = c0 + cell["colspan"] - 1
            out.append({
                "row": cell["row"],
                "col": cell["col"],
                "rowspan": cell["rowspan"],
                "colspan": cell["colspan"],
                "page_idx": region["page_idx"],
                "bbox": [
                    cbands[c0][0],
                    rbands[r0][0],
                    cbands[c1][1],
                    rbands[r1][1],
                ],
                "text": cell["text"],
            })
    out.sort(key=lambda item: (item["row"], item["col"]))
    return out
