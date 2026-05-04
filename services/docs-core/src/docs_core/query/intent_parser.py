"""知识查询意图解析。"""
import re
from typing import Dict

from docs_core.query.contracts import TaskType


ROUTE_KEYWORDS: Dict[TaskType, tuple[str, ...]] = {
    "analytic_sql": ("多少", "统计", "汇总", "平均", "最大", "最小", "占比", "排名", "求和"),
    "schema_qa": ("字段", "列", "口径", "指标", "哪个表", "schema", "sales_amount"),
    "table_qa": ("表", "表格", "行", "列", "单元格", "等级", "代码", "取值", "枚举", "参数表"),
    "locate_qa": ("哪一页", "哪一章", "哪一节", "在哪里", "位置"),
    "definition_qa": ("什么是", "定义", "含义", "解释", "公式", "式中", "表示什么", "代表什么"),
    "content_qa": tuple(),
    "mixed": tuple(),
}


# 规范化查询文本，降低简单规则路由的噪声。
def normalize_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


# 提取问题中的条款编号，保持 query 层无 retrieval 循环依赖。
def extract_inline_clause_refs(query: str) -> tuple[str, ...]:
    return tuple(re.findall(r"\d+(?:\.\d+){1,4}", query or ""))


# 判断问题是否更像表格取值、枚举映射或行列查找。
def looks_like_table_query(query: str) -> bool:
    normalized_query = normalize_query(query)
    explicit_markers = ("表", "表格", "行", "列", "单元格", "等级", "代码", "枚举", "参数表")
    if any(marker in normalized_query for marker in explicit_markers):
        return True
    lookup_markers = ("取值", "对应值", "对应关系", "哪个等级", "哪个代码")
    if any(marker in normalized_query for marker in lookup_markers):
        return True
    return bool(re.search(r"[A-Za-z_][A-Za-z0-9_]{1,}\s*(?:\([^)]+\))?", query or ""))


# 基于规则推断本次查询的任务类型。
def parse_intent(query: str, mode: str = "auto") -> TaskType:
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

    if extract_inline_clause_refs(query):
        if any(marker in normalized_query for marker in ("内容", "是什么", "定义", "含义", "解释", "公式")):
            return "definition_qa"

    if looks_like_table_query(query):
        table_keywords = ROUTE_KEYWORDS.get("table_qa", tuple())
        if any(keyword in normalized_query for keyword in table_keywords) or any(
            marker in normalized_query for marker in ("多少", "什么值", "取值", "对应值")
        ):
            return "table_qa"

    for task_type, keywords in ROUTE_KEYWORDS.items():
        if not keywords:
            continue
        if any(keyword in normalized_query for keyword in keywords):
            return task_type
    return "content_qa"
