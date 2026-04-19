"""知识查询路由器。"""
from typing import Dict

from docs_core.retrieval.contracts import TaskType


ROUTE_KEYWORDS: Dict[TaskType, tuple[str, ...]] = {
    "analytic_sql": ("多少", "统计", "汇总", "平均", "最大", "最小", "占比", "排名", "求和"),
    "schema_qa": ("字段", "列", "口径", "指标", "哪个表", "schema", "sales_amount"),
    "table_qa": ("表", "表格", "行", "列", "单元格", "等级", "代码"),
    "locate_qa": ("哪一页", "哪一章", "哪一节", "在哪里", "位置"),
    "definition_qa": ("什么是", "定义", "含义", "解释"),
    "content_qa": tuple(),
    "mixed": tuple(),
}


# 规范化查询文本，降低简单规则路由的噪声。
def normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


# 基于规则推断本次查询的任务类型。
def route_query(query: str, mode: str = "auto") -> TaskType:
    normalized_query = normalize_query(query)
    if not normalized_query:
        return "content_qa"

    if mode and mode != "auto":
        if mode in ROUTE_KEYWORDS:
            return mode  # type: ignore[return-value]
        if mode == "retrieval":
            return "content_qa"
        if mode == "sql":
            return "analytic_sql"
        if mode == "schema":
            return "schema_qa"
        if mode == "table":
            return "table_qa"

    for task_type, keywords in ROUTE_KEYWORDS.items():
        if not keywords:
            continue
        if any(keyword in normalized_query for keyword in keywords):
            return task_type
    return "content_qa"
