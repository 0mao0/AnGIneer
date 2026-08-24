# table_cells 单元格级坐标（估算版 A1）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 `doc_blocks_graph.jsonl` 的 table 块新增 `table_cells`（单元格级 bbox，估算）与 `table_cells_source`，服务端统一估算并透出给 docs-api。

**Architecture:** 新增一个共享模块 `table_cells.py`（网格解析 + 行/列条带估算 + 跨页分配 + enrich），照 `table_semantics` 的链路接入：04 结构化阶段生成 → 05 重建透传/编辑失效 → docs-api 块模型透出；另加一个一次性回填脚本处理存量 jsonl。

**Tech Stack:** Python 3.10+，标准库 `html.parser`，pytest，无新第三方依赖。

---

## File Structure

- Create: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py` — 核心算法（网格解析、条带估算、跨页分配、enrich）。
- Create: `services/docs-core/tests/test_table_cells.py` — 核心算法单测。
- Create: `services/docs-core/scripts/backfill_table_cells.py` — 存量 jsonl 回填。
- Modify: `services/docs-core/src/docs_core/step04_structure/solo2json_pipeline.py` — 04 调用 enrich。
- Modify: `services/docs-core/src/docs_core/step05_sqlite_fts/rebuild/graph_rebuilder.py` — 05 透传。
- Modify: `services/docs-core/src/docs_core/step05_sqlite_fts/graph_editor.py` — 编辑失效清空。
- Modify: `services/docs-api/models/v1_responses.py` — Block 模型加字段。
- Modify: `services/docs-api/routes/v1/documents.py` — Block 构造透出。
- Modify: `services/docs-api/docs_routes.py` — 摘要 heavy_keys 排除。

测试命令约定（在 `services/docs-core` 目录下执行，`tests/conftest.py` 已把 `src` 加入 `sys.path`）：

```bash
cd services/docs-core
python -m pytest tests/test_table_cells.py -v
```

---

### Task 1: 网格解析 `parse_table_grid`

**Files:**
- Create: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

创建 `services/docs-core/tests/test_table_cells.py`：

```python
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`ModuleNotFoundError: No module named 'docs_core.step04_structure.shared.table_cells'`

- [ ] **Step 3: 实现最小代码**

创建 `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（3 个测试）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/shared/table_cells.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): add table grid parser for cell-level geometry"
```

---

### Task 2: 行/列条带估算

**Files:**
- Modify: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

在 `test_table_cells.py` 追加：

```python
from docs_core.step04_structure.shared.table_cells import (
    estimate_col_bands,
    estimate_row_bands,
)


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`ImportError: cannot import name 'estimate_row_bands'`

- [ ] **Step 3: 实现**

在 `table_cells.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（6 个测试）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/shared/table_cells.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): estimate row and column bands by text length"
```

---

### Task 3: 区域归一化与跨页行分配

**Files:**
- Modify: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

在 `test_table_cells.py` 追加：

```python
from docs_core.step04_structure.shared.table_cells import (
    _assign_rows_to_regions,
    _horizontal_overlap,
    _normalize_regions,
)


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`ImportError: cannot import name '_normalize_regions'`

- [ ] **Step 3: 实现**

在 `table_cells.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（9 个测试）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/shared/table_cells.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): add cross-page region normalization and row assignment"
```

---

### Task 4: `build_table_cells`（单元格 bbox 组装）

**Files:**
- Modify: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

在 `test_table_cells.py` 追加：

```python
from docs_core.step04_structure.shared.table_cells import build_table_cells


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`ImportError: cannot import name 'build_table_cells'`

- [ ] **Step 3: 实现**

在 `table_cells.py` 末尾追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（12 个测试）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/shared/table_cells.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): assemble cell-level bbox from grid and band estimates"
```

---

### Task 5: `enrich_graph_nodes_table_cells` + 空壳匹配

**Files:**
- Modify: `services/docs-core/src/docs_core/step04_structure/shared/table_cells.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

在 `test_table_cells.py` 追加：

```python
from docs_core.step04_structure.shared.table_cells import (
    enrich_graph_nodes_table_cells,
)


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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`ImportError: cannot import name 'enrich_graph_nodes_table_cells'`

- [ ] **Step 3: 实现**

在 `table_cells.py` 末尾追加：

```python
def _resolve_regions_for_node(node, bbox, by_page):
    page_bboxes = node.get("page_bboxes")
    if page_bboxes and isinstance(page_bboxes, list):
        regions = _normalize_regions(page_bboxes)
        if regions:
            return regions
    regions = [{"page_idx": int(node.get("page_idx") or 0), "bbox": [float(v) for v in bbox[:4]]}]
    page_idx = int(node.get("page_idx") or 0)
    while True:
        for candidate in by_page.get(page_idx + 1, []):
            if str(candidate.get("block_type") or "").strip() != "table":
                continue
            if parse_table_grid(candidate.get("table_html") or "").get("cells"):
                continue
            candidate_bbox = candidate.get("bbox")
            if not isinstance(candidate_bbox, (list, tuple)) or len(candidate_bbox) < 4:
                continue
            if not _horizontal_overlap(bbox, candidate_bbox):
                continue
            regions.append({
                "page_idx": page_idx + 1,
                "bbox": [float(v) for v in candidate_bbox[:4]],
            })
            page_idx += 1
            break
        else:
            break
    return regions


def enrich_graph_nodes_table_cells(nodes):
    stats = {"total_tables": 0, "enriched": 0, "skipped": 0}
    if not nodes:
        return nodes, stats
    updated = [dict(node) for node in nodes]
    by_page: Dict[int, List[Dict[str, Any]]] = {}
    for node in updated:
        by_page.setdefault(int(node.get("page_idx") or 0), []).append(node)
    for node in updated:
        if str(node.get("block_type") or "").strip() != "table":
            continue
        stats["total_tables"] += 1
        html = node.get("table_html") or ""
        grid = parse_table_grid(html)
        if not grid["cells"]:
            stats["skipped"] += 1
            continue
        bbox = node.get("bbox")
        if not isinstance(bbox, (list, tuple)) or len(bbox) < 4:
            stats["skipped"] += 1
            continue
        regions = _resolve_regions_for_node(node, bbox, by_page)
        cells = build_table_cells(
            html,
            bbox,
            page_idx=int(node.get("page_idx") or 0),
            regions=regions,
        )
        if not cells:
            stats["skipped"] += 1
            continue
        node["table_cells"] = cells
        node["table_cells_source"] = TABLE_CELLS_SOURCE
        stats["enriched"] += 1
    return updated, stats
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（15 个测试）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/shared/table_cells.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): enrich table nodes with cell-level geometry"
```

---

### Task 6: 接入 04 结构化阶段

**Files:**
- Modify: `services/docs-core/src/docs_core/step04_structure/solo2json_pipeline.py`

- [ ] **Step 1: 修改 enrich 调用**

在 `solo2json_pipeline.py` 中，`enrich_graph_nodes_table_semantics(result.nodes)` 之后、`stats = {` 之前插入：

```python
        from docs_core.step04_structure.shared.table_cells import (
            enrich_graph_nodes_table_cells,
        )
        result.nodes, table_cells_stats = enrich_graph_nodes_table_cells(result.nodes)
        _emit_step(on_step, "表格单元格坐标 enrich", "done", f"{table_cells_stats['enriched']} tables")
```

并在 `stats = { ... }` 字典末尾（`"table_semantics": table_stats,` 之后）增加：

```python
        "table_cells": table_cells_stats,
```

- [ ] **Step 2: 语法与导入自检**

```bash
cd services/docs-core && python -m py_compile src/docs_core/step04_structure/solo2json_pipeline.py
```
Expected: 无输出、退出码 0

- [ ] **Step 3: 提交**

```bash
git add services/docs-core/src/docs_core/step04_structure/solo2json_pipeline.py
git commit -m "feat(docs-core): emit table_cells during step04 structure"
```

---

### Task 7: 05 重建透传 + 编辑失效

**Files:**
- Modify: `services/docs-core/src/docs_core/step05_sqlite_fts/rebuild/graph_rebuilder.py`
- Modify: `services/docs-core/src/docs_core/step05_sqlite_fts/graph_editor.py`
- Test: `services/docs-core/tests/test_table_cells.py`

- [ ] **Step 1: 写失败测试**

在 `test_table_cells.py` 追加：

```python
from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import adapt_graph_node


def test_adapt_graph_node_carries_table_cells() -> None:
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
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: FAIL，`adapted["table_cells"]` 不存在（KeyError）

- [ ] **Step 3: 实现透传**

在 `graph_rebuilder.py` 的 `adapt_graph_node` 返回字典中，`"table_semantics": raw_node.get("table_semantics"),` 之后插入两行：

```python
        "table_cells": raw_node.get("table_cells"),
        "table_cells_source": raw_node.get("table_cells_source"),
```

- [ ] **Step 4: 实现编辑失效**

在 `graph_editor.py` 的 `_invalidate_edited_table_semantics` 中，`node.pop("table_semantics", None)` 之后插入：

```python
            node.pop("table_cells", None)
            node.pop("table_cells_source", None)
```

- [ ] **Step 5: 运行测试确认通过**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py -v
```
Expected: PASS（16 个测试）

- [ ] **Step 6: 提交**

```bash
git add services/docs-core/src/docs_core/step05_sqlite_fts/rebuild/graph_rebuilder.py services/docs-core/src/docs_core/step05_sqlite_fts/graph_editor.py services/docs-core/tests/test_table_cells.py
git commit -m "feat(docs-core): pass through and invalidate table_cells in step05"
```

---

### Task 8: docs-api 透出

**Files:**
- Modify: `services/docs-api/models/v1_responses.py`
- Modify: `services/docs-api/routes/v1/documents.py`
- Modify: `services/docs-api/docs_routes.py`

- [ ] **Step 1: 模型加字段**

在 `v1_responses.py` 的 `class Block(BaseModel)` 中，`math_latex` 之后插入：

```python
    table_cells: Optional[List[Dict[str, Any]]] = Field(None)
    table_cells_source: Optional[str] = Field(None)
```

若文件顶部未导入 `Dict` / `Any`，在 `from typing import ...` 处补上 `Any, Dict`。

- [ ] **Step 2: 构造透出**

在 `documents.py` 的 `blocks.append(Block(...))` 中，`math_latex=n.get("math_content"),` 之后插入：

```python
            table_cells=n.get("table_cells"),
            table_cells_source=n.get("table_cells_source"),
```

- [ ] **Step 3: 摘要排除**

在 `docs_routes.py` 的 `get_doc_blocks_graph_summary` 中，`heavy_keys` 集合里 `"math_content",` 之后插入：

```python
            "table_cells", "table_cells_source",
```

- [ ] **Step 4: 语法自检**

```bash
cd services/docs-api && python -m py_compile models/v1_responses.py routes/v1/documents.py docs_routes.py
```
Expected: 无输出、退出码 0

- [ ] **Step 5: 提交**

```bash
git add services/docs-api/models/v1_responses.py services/docs-api/routes/v1/documents.py services/docs-api/docs_routes.py
git commit -m "feat(docs-api): expose table_cells on block responses"
```

---

### Task 9: 存量回填脚本

**Files:**
- Create: `services/docs-core/scripts/backfill_table_cells.py`

- [ ] **Step 1: 写脚本**

创建 `services/docs-core/scripts/backfill_table_cells.py`（镜像 `backfill_markdown_projection.py` 的遍历方式）：

```python
"""存量文档回填：给已有 doc_blocks_graph.jsonl 的 table 块补算 table_cells。

用法（services/docs-core 下）：
    python scripts/backfill_table_cells.py
幂等：重复执行结果一致，其余字段不变。
"""
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import docs_core.paths as paths  # noqa: E402
from docs_core.step04_structure.shared.table_cells import (  # noqa: E402
    enrich_graph_nodes_table_cells,
)


def backfill_document(library_id: str, doc_id: str) -> bool:
    jsonl_path = paths.get_graph_jsonl_path(library_id, doc_id)
    if not jsonl_path.exists():
        return False
    nodes = []
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                nodes.append(json.loads(line))
    if not nodes:
        return False
    updated, stats = enrich_graph_nodes_table_cells(nodes)
    if not stats["enriched"]:
        return False
    with open(jsonl_path, "w", encoding="utf-8") as f:
        for node in updated:
            f.write(json.dumps(node, ensure_ascii=False) + "\n")
    return True


def main() -> None:
    root = paths.resolve_knowledge_base_dir() / "libraries"
    count = 0
    for lib_dir in root.iterdir():
        if not lib_dir.is_dir():
            continue
        documents = lib_dir / "documents"
        if not documents.is_dir():
            continue
        for doc_dir in documents.iterdir():
            if (doc_dir / "parsed" / "doc_blocks_graph.jsonl").exists():
                if backfill_document(lib_dir.name, doc_dir.name):
                    count += 1
                    print(f"backfilled {lib_dir.name}/{doc_dir.name}")
    print(f"total {count} documents")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 幂等验证（先 dry 看会命中哪些文档）**

```bash
cd services/docs-core && python scripts/backfill_table_cells.py
```
Expected: 打印 `backfilled ...` 与 `total N documents`

- [ ] **Step 3: 二次执行确认幂等**

```bash
cd services/docs-core && python scripts/backfill_table_cells.py
```
Expected: `total 0 documents`（已被回填的文档第二次跳过）

- [ ] **Step 4: 抽样核对字段**

```bash
cd services/docs-core && python -c "import json; n=[json.loads(l) for l in open('../../data/knowledge_base/libraries/lib-DredgeAI-a5e1/documents/v1-eea216bb6f11/parsed/doc_blocks_graph.jsonl', encoding='utf-8')]; t=[x for x in n if x.get('block_type')=='table' and x.get('table_cells')][0]; print(len(t['table_cells']), t['table_cells'][0])"
```
Expected: 输出 `41 {...}`（该文档 41 行前附表，单元格数 > 0，首个单元格含 row/col/bbox/text）

- [ ] **Step 5: 提交**

```bash
git add services/docs-core/scripts/backfill_table_cells.py
git commit -m "feat(docs-core): add backfill script for table_cells"
```

---

### Task 10: 全量回归与构建

- [ ] **Step 1: 运行 docs-core 相关测试**

```bash
cd services/docs-core && python -m pytest tests/test_table_cells.py tests/test_table_semantics_sidecar.py -v
```
Expected: 全部 PASS

- [ ] **Step 2: 运行 harness 确认无回归**

```bash
pnpm harness
```
Expected: 与基线一致（既有 4F/6E 环境问题不变，无新增失败）

- [ ] **Step 3: 构建前端产物（可选，确认无导入破坏）**

```bash
pnpm build:admin
```
Expected: 成功

- [ ] **Step 4: 手工视觉验收（对应 spec 验收标准）**

用 `lib-DredgeAI-a5e1/v1-eea216bb6f11` 这份 41 行前附表：
1. 回填后读取该 table 节点的 `table_cells`，核对 `row/col/text` 与 `table_html` 一致（Task 9 Step 4 已抽查首个单元格，此处重点看含 rowspan 的 10.7 行）。
2. 渲染源 PDF 第 5 页（0-based 4）并叠加 `page_idx==4` 的单元格 bbox，肉眼检查行级对齐；第 6/7 页（0-based 5/6）应只出现各自页归属的单元格。这一步为人工目检，无自动化脚本。
