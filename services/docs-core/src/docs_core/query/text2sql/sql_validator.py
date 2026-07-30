"""Text-to-SQL 的 SQL 校验。"""
import re


ALLOWED_TABLES = {
    "canonical_documents",
    "canonical_chunks",
    "canonical_tables",
    "canonical_blocks",
    "canonical_outlines",
}

ALLOWED_FILTER_COLUMNS = {
    "canonical_chunks": {
        "doc_id", "chunk_type", "section_path", "page_start", "page_end",
        "inherited_chapter", "entity_tags_json", "conditions_json",
        "exam_tags_json", "clause_id", "version",
    },
    "canonical_blocks": {
        "doc_id", "block_type", "section_path", "page_idx",
        "inherited_chapter", "entity_tags_json", "conditions_json",
        "exam_tags_json", "clause_id", "source",
    },
    "canonical_documents": {
        "doc_id", "library_id", "title", "source_file_type", "language", "status",
    },
    "canonical_tables": {
        "doc_id", "table_type", "page_start", "page_end", "title",
    },
    "canonical_outlines": {
        "doc_id", "level", "title", "section_path", "page_idx",
    },
}


# 校验生成 SQL 是否满足只读白名单约束。
def validate_sql(sql: str) -> tuple[bool, str]:
    normalized_sql = " ".join((sql or "").strip().split())
    if not normalized_sql:
        return False, "empty_sql"
    if ";" in normalized_sql:
        return False, "semicolon_not_allowed"
    if not normalized_sql.upper().startswith("SELECT"):
        return False, "only_select_supported"
    if any(keyword in normalized_sql.upper() for keyword in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "ATTACH ")):
        return False, "write_operation_not_allowed"
    table_match = re.search(r"FROM\s+([A-Za-z_][A-Za-z0-9_]*)", normalized_sql, flags=re.IGNORECASE)
    if not table_match:
        return False, "missing_table_name"
    table_name = table_match.group(1)
    if table_name not in ALLOWED_TABLES:
        return False, f"table_not_allowed:{table_name}"
    where_columns = re.findall(r"(\w+)\s*(?:=|!=|<>|LIKE|IN|IS)\s", normalized_sql, flags=re.IGNORECASE)
    allowed = ALLOWED_FILTER_COLUMNS.get(table_name, set())
    for col in where_columns:
        if col.upper() in ("AND", "OR", "NOT", "WHERE", "SELECT", "FROM"):
            continue
        if col not in allowed:
            return False, f"column_not_allowed:{col}"
    return True, "ok"
