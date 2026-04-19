"""表格分类器。"""
from typing import Dict, List


TABLE_TYPE_NUMERIC_DENSE = "numeric_dense"
TABLE_TYPE_TEXT_DENSE = "text_dense"
TABLE_TYPE_HYBRID = "hybrid"
TABLE_TYPE_MAPPING_ENUM = "mapping_enum"


# 归一化单元格文本，便于后续做规则统计。
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
