"""Text-to-SQL 的结果解释。"""

from docs_core.query.text2sql.sql_planner import SqlPlan


# 将 SQL 计划与执行结果组织成用户可读说明。
def explain_sql_result(plan: SqlPlan, result_preview: dict[str, object]) -> str:
    rows = list(result_preview.get("rows") or [])
    total_count = 0
    if rows:
        total_count = int(rows[0].get("total_count", 0) or 0)
    if not plan.supported:
        return "当前 Text-to-SQL 仅支持对象计数类统计问题，复杂聚合能力后续补齐。"
    return f"{plan.description}结果为 {total_count}。"
