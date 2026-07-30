"""Text-to-SQL 的 SQL 生成。"""

from docs_core.query.text2sql.sql_planner import SqlPlan


# 将 SQL 计划转换为最终待执行 SQL 文本与参数。
def generate_sql(plan: SqlPlan) -> tuple[str, tuple[object, ...]]:
    if not plan.supported:
        return "", ()
    return plan.generated_sql, plan.parameters
