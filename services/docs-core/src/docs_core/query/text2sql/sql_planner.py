"""Text-to-SQL 的执行规划。"""
from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class SqlPlan:
    """结构化查询计划。"""

    supported: bool
    metric: str
    table_name: str
    generated_sql: str = ""
    parameters: Tuple[object, ...] = ()
    description: str = ""
    reason: str = ""
    linked_schema: Dict[str, object] = field(default_factory=dict)


# 基于 link_schema 结果生成最小 SQL 计划。
def plan_sql(linked_schema: Dict[str, object]) -> SqlPlan:
    supported = bool(linked_schema.get("supported", False))
    metric = str(linked_schema.get("metric") or "")
    table_name = str(linked_schema.get("table_name") or "")
    description = str(linked_schema.get("description") or "")
    if not supported or not table_name:
        return SqlPlan(
            supported=False,
            metric=metric,
            table_name=table_name,
            description=description,
            reason=str(linked_schema.get("reason") or "unsupported_sql_plan"),
            linked_schema=linked_schema,
        )

    filters = dict(linked_schema.get("filters") or {})
    doc_ids = [str(item) for item in filters.get("doc_ids", []) if item]
    library_id = str(filters.get("library_id") or "default")
    where_clauses: List[str] = []
    parameters: List[object] = []

    if doc_ids:
        placeholders = ", ".join("?" for _ in doc_ids)
        if table_name == "canonical_documents":
            where_clauses.append(f"doc_id IN ({placeholders})")
        else:
            where_clauses.append(f"doc_id IN ({placeholders})")
        parameters.extend(doc_ids)
    elif table_name == "canonical_documents":
        where_clauses.append("library_id = ?")
        parameters.append(library_id)
    else:
        where_clauses.append("doc_id IN (SELECT doc_id FROM canonical_documents WHERE library_id = ?)")
        parameters.append(library_id)

    sql = f"SELECT COUNT(*) AS total_count FROM {table_name}"
    if where_clauses:
        sql = f"{sql} WHERE {' AND '.join(where_clauses)}"
    return SqlPlan(
        supported=True,
        metric=metric,
        table_name=table_name,
        generated_sql=sql,
        parameters=tuple(parameters),
        description=description,
        linked_schema=linked_schema,
    )
