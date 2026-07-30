"""表格内容表示与分类工具。"""
from typing import Any, Dict, List


TABLE_TYPE_NUMERIC_DENSE = "numeric_dense"
TABLE_TYPE_TEXT_DENSE = "text_dense"
TABLE_TYPE_HYBRID = "hybrid"
TABLE_TYPE_MAPPING_ENUM = "mapping_enum"


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


# 归一化表头，生成适合索引的列定义。
def build_table_schema(headers: List[List[object]]) -> List[str]:
    if not headers:
        return []
    flattened: List[str] = []
    for row in headers:
        for cell in row:
            normalized = normalize_table_cell(cell)
            if normalized:
                flattened.append(normalized)
    return flattened


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


# 生成面向检索的行级文本表示。
def build_text_row_chunks(title: str, headers: List[str], rows: List[List[object]]) -> List[str]:
    row_chunks: List[str] = []
    for row in rows:
        normalized_row = [normalize_table_cell(cell) for cell in row]
        if not any(normalized_row):
            continue
        pairs = []
        for index, cell in enumerate(normalized_row):
            header = headers[index] if index < len(headers) else f"列{index + 1}"
            if cell:
                pairs.append(f"{header}: {cell}")
        if pairs:
            row_chunks.append(f"{title} | " + " | ".join(pairs))
    return row_chunks


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
        "table_text_chunks": [],
    }

    if table_type in {TABLE_TYPE_TEXT_DENSE, TABLE_TYPE_HYBRID, TABLE_TYPE_MAPPING_ENUM}:
        payload["table_text_chunks"] = build_text_row_chunks(title, schema_headers, body_rows)
    return payload


__all__ = [
    "TABLE_TYPE_HYBRID",
    "TABLE_TYPE_MAPPING_ENUM",
    "TABLE_TYPE_NUMERIC_DENSE",
    "TABLE_TYPE_TEXT_DENSE",
    "build_table_representations",
    "build_table_row_keys",
    "build_table_schema",
    "build_text_row_chunks",
    "classify_table",
    "extract_table_features",
    "is_numeric_like",
    "normalize_table_cell",
]
