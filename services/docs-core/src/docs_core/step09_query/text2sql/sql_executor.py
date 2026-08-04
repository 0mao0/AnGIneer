"""Text-to-SQL SQL 执行"""
from pathlib import Path
from typing import Any, Dict, Optional

from docs_core.paths import resolve_knowledge_index_db_path
from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection


# 执行通过校验的只SQL，并返回最小结果预览
def execute_sql(sql: str, parameters: tuple[object, ...], db_path: Optional[Path] = None) -> Dict[str, Any]:
    if not sql:
        return {
            "rows": [],
            "row_count": 0,
        }
    target_db_path = db_path or resolve_knowledge_index_db_path()
    with create_connection(target_db_path) as conn:
        cursor = conn.execute(sql, parameters)
        rows = [dict(row) for row in cursor.fetchall()]
    return {
        "rows": rows,
        "row_count": len(rows),
    }
