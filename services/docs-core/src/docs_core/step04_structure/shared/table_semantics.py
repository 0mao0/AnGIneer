"""表格内容表示与分类工具（归位 step04/shared：04 生成、05 透传/兜底）。

语义层契约：
- 04 落 jsonl 前由 ``enrich_graph_nodes_table_semantics`` 给 table 节点写入
  ``table_semantics`` 旁路字段（table_type / table_meta / table_schema /
  table_row_keys / table_summary / table_text_chunks / version）；
- 05 重建 ``CanonicalTable`` 时优先透传旁路，缺失才用 ``enrich_canonical_table``
  兜底重算，避免两套逻辑漂移。

原始字段（table_html / content_json）永不修改，旁路字段只做语义指引。
"""
import re
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from docs_core.models.types import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
)
from docs_core.step04_structure.shared.table_cells import parse_table_grid

if TYPE_CHECKING:
    from docs_core.models.types import CanonicalTable


TABLE_SEMANTICS_VERSION = "0.2.0"


# 归一化单元格文本，便于后续做规则统计和表示构建。
def normalize_table_cell(value: object) -> str:
    if value is None:
        return ""
    return str(value).strip()


# 判断单元格是否以数值为主。
def is_numeric_like(cell: str) -> bool:
    if not cell:
        return False
    allowed = set("0123456789.+-%/,:() ")
    return all(char in allowed for char in cell)


# 计算表格分类特征。
def extract_table_features(rows: List[List[object]]) -> Dict[str, float]:
    normalized_rows = [[normalize_table_cell(cell) for cell in row] for row in rows if row]
    if not normalized_rows:
        return {
            "numeric_ratio": 0.0,
            "avg_cell_length": 0.0,
            "long_text_cell_ratio": 0.0,
            "first_col_uniqueness": 0.0,
            "unit_density": 0.0,
        }

    flat_cells = [cell for row in normalized_rows for cell in row if cell]
    total_cells = len(flat_cells) or 1
    numeric_cells = sum(1 for cell in flat_cells if is_numeric_like(cell))
    long_text_cells = sum(1 for cell in flat_cells if len(cell) >= 20)
    avg_cell_length = sum(len(cell) for cell in flat_cells) / total_cells if flat_cells else 0.0

    first_col_values = [row[0] for row in normalized_rows if row and row[0]]
    unique_first_col = len(set(first_col_values))
    first_col_uniqueness = unique_first_col / max(1, len(first_col_values))

    units = ("%", "MPa", "kN", "m", "mm", "kg", "m3", "km", "kPa")
    unit_hits = sum(1 for cell in flat_cells if any(unit in cell for unit in units))

    return {
        "numeric_ratio": numeric_cells / total_cells,
        "avg_cell_length": avg_cell_length,
        "long_text_cell_ratio": long_text_cells / total_cells,
        "first_col_uniqueness": first_col_uniqueness,
        "unit_density": unit_hits / total_cells,
    }


# 基于规则判断表格类型。
def classify_table(rows: List[List[object]]) -> str:
    features = extract_table_features(rows)
    numeric_ratio = features["numeric_ratio"]
    long_text_ratio = features["long_text_cell_ratio"]
    first_col_uniqueness = features["first_col_uniqueness"]

    if long_text_ratio >= 0.30 and numeric_ratio < 0.40:
        return TABLE_TYPE_TEXT_DENSE
    if numeric_ratio >= 0.60 and long_text_ratio <= 0.10:
        return TABLE_TYPE_NUMERIC_DENSE
    if first_col_uniqueness >= 0.80 and 0.05 <= long_text_ratio <= 0.40 and numeric_ratio <= 0.50:
        return TABLE_TYPE_MAPPING_ENUM
    return TABLE_TYPE_HYBRID


# 把表格 HTML 解析成规整二维数组（正确展开 colspan 与 rowspan 占位）。
def parse_table_rows(table_html: str) -> List[List[str]]:
    grid = parse_table_grid(table_html)
    rows_count = int(grid.get("rows_count") or 0)
    cols_count = int(grid.get("cols_count") or 0)
    if rows_count <= 0 or cols_count <= 0:
        return []
    rows: List[List[str]] = [[""] * cols_count for _ in range(rows_count)]
    for cell in grid.get("cells", []):
        text = str(cell.get("text") or "")
        row = int(cell.get("row") or 0)
        col = int(cell.get("col") or 0)
        rowspan = max(1, int(cell.get("rowspan") or 1))
        colspan = max(1, int(cell.get("colspan") or 1))
        for r in range(row, min(row + rowspan, rows_count)):
            for c in range(col, min(col + colspan, cols_count)):
                rows[r][c] = text
    return [row for row in rows if any(normalize_table_cell(cell) for cell in row)]


# 判断表头行是否存在重复的父列名（说明下方有子列分组）。
def _has_repeated_header(row: List[object]) -> bool:
    cells = [normalize_table_cell(cell) for cell in row]
    nonempty = [cell for cell in cells if cell]
    return len(nonempty) != len(set(nonempty))


# 判断第二行是否为子表头：第一列应是空占位或编号，其余列短编号/符号。
def _is_subheader_row(row: List[object]) -> bool:
    cells = [normalize_table_cell(cell) for cell in row]
    nonempty = [cell for cell in cells if cell]
    if not nonempty:
        return False
    first = cells[0] if cells else ""
    if first and re.search(r"\w{2,}", first, flags=re.UNICODE):
        return False
    for cell in nonempty:
        if len(cell) > 6:
            return False
    return True


# 识别单行/多行表头，返回 (header_rows, body_rows)。
def split_header_body(rows: List[List[str]]) -> Tuple[List[List[str]], List[List[str]]]:
    if not rows:
        return [], []
    if len(rows) >= 2 and _has_repeated_header(rows[0]) and _is_subheader_row(rows[1]):
        return rows[:2], rows[2:]
    return rows[:1], rows[1:]


# 归一化表头，生成适合索引的列定义；多行表头按列合并。
def build_table_schema(headers: List[List[object]]) -> List[str]:
    if not headers:
        return []
    ncols = max((len(row) for row in headers), default=0)
    schema: List[str] = []
    for col in range(ncols):
        parts: List[str] = []
        prev: Optional[str] = None
        for row in headers:
            cell = normalize_table_cell(row[col]) if col < len(row) else ""
            if cell and cell != prev:
                parts.append(cell)
            if cell:
                prev = cell
        schema.append(" ".join(parts))
    return schema


# 提取第一列主键项，便于数值型表做行定位。
def build_table_row_keys(rows: List[List[object]]) -> List[str]:
    row_keys: List[str] = []
    for row in rows:
        if not row:
            continue
        first_cell = normalize_table_cell(row[0])
        if first_cell:
            row_keys.append(first_cell)
    return row_keys


# 生成面向检索的行级文本表示；数值作为载荷跟随行键与列头进入上下文。
def build_text_row_chunks(title: str, headers: List[str], rows: List[List[object]]) -> List[str]:
    short_title = title if len(title) <= 60 else title[:60] + "…"
    row_chunks: List[str] = []
    for row in rows:
        normalized_row = [normalize_table_cell(cell) for cell in row]
        if not any(normalized_row):
            continue
        pairs: List[str] = []
        for index, cell in enumerate(normalized_row):
            header = headers[index] if index < len(headers) else f"列{index + 1}"
            if not header or not header.strip():
                header = "行标签"
            if cell:
                pairs.append(f"{header}: {cell}")
        if pairs:
            prefix = f"{short_title} | " if short_title else ""
            row_chunks.append(prefix + " | ".join(pairs))
    return row_chunks


# 生成整表文本化表示，用于需要遍历/比较整张表的检索与问答。
def build_table_full_text(
    title: str,
    header_rows: List[List[object]],
    body_rows: List[List[object]],
) -> str:
    schema = build_table_schema(header_rows or body_rows[:1])
    lines: List[str] = []
    if title:
        lines.append(f"表：{title}")
    header_line = "、".join(header for header in schema if header)
    if header_line:
        lines.append(f"列：{header_line}")
    for row in body_rows:
        normalized_row = [normalize_table_cell(cell) for cell in row]
        if not any(normalized_row):
            continue
        pairs: List[str] = []
        for index, cell in enumerate(normalized_row):
            header = schema[index] if index < len(schema) else f"列{index + 1}"
            if not header or not header.strip():
                header = "行标签"
            if cell:
                pairs.append(f"{header}: {cell}")
        if pairs:
            lines.append(" | ".join(pairs))
    return "\n".join(lines)


# 生成统一表格表示，供后续不同索引层消费。
def build_table_representations(
    title: str,
    header_rows: List[List[object]],
    body_rows: List[List[object]],
) -> Dict[str, Any]:
    table_type = classify_table(header_rows + body_rows)
    schema_headers = build_table_schema(header_rows or body_rows[:1])
    row_keys = build_table_row_keys(body_rows)
    summary = f"表格《{title or '未命名表格'}》包含 {len(body_rows)} 行、{max((len(row) for row in body_rows), default=0)} 列。"
    if schema_headers:
        summary += " 列：" + "、".join(header for header in schema_headers if header)

    payload: Dict[str, Any] = {
        "table_type": table_type,
        "table_meta": {
            "title": title,
            "row_count": len(body_rows),
            "col_count": max((len(row) for row in body_rows), default=0),
        },
        "table_schema": schema_headers,
        "table_row_keys": row_keys,
        "table_summary": summary,
        "table_text_chunks": build_text_row_chunks(title, schema_headers, body_rows),
    }
    return payload


# 生成写入 jsonl 的 table_semantics 旁路字段。
def build_table_semantics_sidecar(
    title: str,
    header_rows: List[List[object]],
    body_rows: List[List[object]],
    *,
    version: str = TABLE_SEMANTICS_VERSION,
) -> Dict[str, Any]:
    return {
        **build_table_representations(title, header_rows, body_rows),
        "version": version,
    }


def _node_table_html(node: Dict[str, Any]) -> str:
    content = node.get("content_json") if isinstance(node.get("content_json"), dict) else {}
    return str(
        node.get("table_html")
        or content.get("html")
        or ""
    ).strip()


def _node_table_title(node: Dict[str, Any]) -> str:
    caption = str(node.get("caption") or "").strip()
    if caption:
        return caption
    content = node.get("content_json") if isinstance(node.get("content_json"), dict) else {}
    fragments: List[str] = []
    for item in content.get("table_caption") or []:
        if isinstance(item, dict):
            value = str(item.get("content") or "").strip()
        else:
            value = str(item).strip()
        if value:
            fragments.append(value)
    return "".join(fragments).strip()


# 04 建块后、落 jsonl 前调用：给 table 节点计算并写入 table_semantics 旁路字段。
def enrich_graph_nodes_table_semantics(
    nodes: List[Dict[str, Any]],
    *,
    version: str = TABLE_SEMANTICS_VERSION,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """给表格节点写 ``table_semantics`` 旁路，原始字段保持不变。"""
    stats: Dict[str, Any] = {"total_tables": 0, "enriched": 0, "skipped": 0}
    if not nodes:
        return nodes, stats

    updated = [dict(node) for node in nodes]
    for node in updated:
        if str(node.get("block_type") or "").strip() != "table":
            continue
        stats["total_tables"] += 1
        html = _node_table_html(node)
        rows = parse_table_rows(html)
        if not rows:
            stats["skipped"] += 1
            continue
        header_rows, body_rows = split_header_body(rows)
        node["table_semantics"] = build_table_semantics_sidecar(
            _node_table_title(node),
            header_rows,
            body_rows,
            version=version,
        )
        stats["enriched"] += 1
    return updated, stats


# 语义层后端无关入口：消费 CanonicalTable，产物沿用现有专用字段，
# 不新增列。返回 dict 与 build_table_representations 的专用字段对齐。
def enrich_canonical_table(table: "CanonicalTable") -> Dict[str, Any]:
    if table is None:
        return {
            "table_type": TABLE_TYPE_HYBRID,
            "summary": "",
            "row_keys": [],
            "text_chunks": [],
        }
    representations = build_table_representations(
        table.title,
        table.header_rows,
        table.body_rows,
    )
    return {
        "table_type": representations["table_type"],
        "summary": str(representations.get("table_summary") or ""),
        "row_keys": [str(item) for item in representations.get("table_row_keys", [])],
        "text_chunks": [str(item) for item in representations.get("table_text_chunks", [])],
    }


__all__ = [
    "TABLE_SEMANTICS_VERSION",
    "TABLE_TYPE_HYBRID",
    "TABLE_TYPE_MAPPING_ENUM",
    "TABLE_TYPE_NUMERIC_DENSE",
    "TABLE_TYPE_TEXT_DENSE",
    "build_table_representations",
    "build_table_row_keys",
    "build_table_schema",
    "build_table_semantics_sidecar",
    "build_table_full_text",
    "build_text_row_chunks",
    "classify_table",
    "enrich_canonical_table",
    "enrich_graph_nodes_table_semantics",
    "extract_table_features",
    "is_numeric_like",
    "normalize_table_cell",
    "parse_table_rows",
    "split_header_body",
]
