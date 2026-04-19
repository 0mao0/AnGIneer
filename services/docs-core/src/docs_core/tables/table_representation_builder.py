"""表格多表示构建器。"""
from typing import Any, Dict, List

from docs_core.tables.table_classifier import classify_table, normalize_table_cell


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


# 生成面向向量检索的行级文本表示。
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

    if table_type in {"text_dense", "hybrid", "mapping_enum"}:
        payload["table_text_chunks"] = build_text_row_chunks(title, schema_headers, body_rows)
    return payload
