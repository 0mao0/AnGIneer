"""Text-to-SQL 的 schema linking，将自然语言问题映射到结构化查询对象。"""
import os
import re
from pathlib import Path
from typing import Dict, List, Optional

from docs_core.knowledge_service import KnowledgeNode
from docs_core.query_protocols.contracts import KnowledgeQueryRequest


COUNT_METRIC_CATALOG = {
    "document_count": {
        "markers": ("多少篇文档", "多少个文档", "多少份文档", "多少篇规范", "多少份规范"),
        "table_name": "canonical_documents",
        "description": "统计文档数量",
    },
    "chunk_count": {
        "markers": ("多少个内容块", "多少个片段", "多少个chunk", "多少段内容"),
        "table_name": "canonical_chunks",
        "description": "统计内容片段数量",
    },
    "table_count": {
        "markers": ("多少张数据表", "多少张结构化表", "多少个表单元"),
        "table_name": "canonical_tables",
        "description": "统计结构化表格数量",
    },
    "block_count": {
        "markers": ("多少个块", "多少个block", "多少个原子块"),
        "table_name": "canonical_blocks",
        "description": "统计原子块数量",
    },
    "outline_count": {
        "markers": ("多少个章节", "多少个目录节点", "多少个标题节点"),
        "table_name": "canonical_outlines",
        "description": "统计大纲节点数量",
    },
}

CLAUSE_ID_PATTERN = re.compile(r"(?:第\s*)?(\d+(?:\.\d+){1,4})\s*(?:条|款|节|章)?")

STANDARD_CODE_PATTERN = re.compile(
    r"(?:GB|GB/T|JGJ|JGJ/T|JTS|JTJ|JTG|JTG/T|JTSC|CJJ|CJJ/T|DL|DL/T|SL|SL/T|NB|NB/T|SY|SY/T|HJ|HJ/T|YB|YB/T|TB|TB/T|SH|SH/T|HG|HG/T|CECS|DB)\s*[/\-]?\s*\d+(?:\s*[-—–]\s*\d+)?",
    re.IGNORECASE,
)

_DEFAULT_ENTITY_KEYWORDS = {
    "边坡": "边坡", "地基": "地基", "挡土墙": "挡土墙",
    "桩基": "桩基", "基坑": "基坑", "隧道": "隧道",
    "路面": "路面", "桥梁": "桥梁", "混凝土": "混凝土",
    "钢筋": "钢筋", "钢结构": "钢结构", "路基": "路基",
    "航道": "航道", "港池": "港池", "码头": "码头",
    "防波堤": "防波堤", "护岸": "护岸", "船闸": "船闸",
    "疏浚": "疏浚", "吹填": "吹填", "围堰": "围堰",
    "导堤": "导堤", "丁坝": "丁坝", "潜堤": "潜堤",
    "抛石": "抛石", "沉箱": "沉箱", "扶壁": "扶壁",
    "板桩": "板桩",
}

_DEFAULT_CONDITION_KEYWORDS = {
    "设计高水位": "设计高水位", "持久状况": "持久状况",
    "短暂状况": "短暂状况", "地震工况": "地震工况",
    "偶然状况": "偶然状况", "标准组合": "标准组合",
    "基本组合": "基本组合", "偶然组合": "偶然组合",
    "准永久组合": "准永久组合",
    "设计低水位": "设计低水位", "极端高水位": "极端高水位",
    "极端低水位": "极端低水位", "乘潮水位": "乘潮水位",
    "施工水位": "施工水位", "设计波高": "设计波高",
    "设计波浪": "设计波浪", "极端波浪": "极端波浪",
    "设计流速": "设计流速", "潮流": "潮流",
    "靠泊": "靠泊", "系泊": "系泊", "撞击": "撞击",
    "疏浚工况": "疏浚工况", "回淤工况": "回淤工况",
}

_DEFAULT_EXAM_KEYWORDS = {
    "承载力": "承载力", "抗倾覆": "抗倾覆", "抗滑移": "抗滑移",
    "沉降": "沉降", "稳定性": "稳定性", "裂缝": "裂缝",
    "变形": "变形", "强度": "强度", "刚度": "刚度", "疲劳": "疲劳",
    "整体稳定": "整体稳定", "抗倾稳定": "抗倾稳定",
    "抗滑稳定": "抗滑稳定", "地基承载力": "地基承载力",
    "基床承载力": "基床承载力", "波浪力": "波浪力",
    "土压力": "土压力", "剩余水压力": "剩余水压力",
    "船舶荷载": "船舶荷载", "撞击力": "撞击力", "系缆力": "系缆力",
}


# 从 YAML 配置文件加载领域关键词字典
def _load_domain_keywords_from_yaml(yaml_path: str) -> Optional[Dict[str, Dict[str, str]]]:
    if not os.path.isfile(yaml_path):
        return None
    try:
        import yaml
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {
            "entity_tags": data.get("entity_tags", {}),
            "conditions": data.get("conditions", {}),
            "exam_tags": data.get("exam_tags", {}),
        }
    except Exception:
        return None


# 获取领域关键词字典，优先从 YAML 配置加载，回退到内置默认值
def _get_domain_keywords() -> Dict[str, Dict[str, str]]:
    project_root = Path(__file__).resolve().parents[4]
    yaml_path = os.environ.get(
        "DOMAIN_KEYWORDS_CONFIG",
        str(project_root / "data" / "configs" / "domain_keywords.yaml"),
    )
    loaded = _load_domain_keywords_from_yaml(yaml_path)
    if loaded:
        return loaded
    return {
        "entity_tags": dict(_DEFAULT_ENTITY_KEYWORDS),
        "conditions": dict(_DEFAULT_CONDITION_KEYWORDS),
        "exam_tags": dict(_DEFAULT_EXAM_KEYWORDS),
    }


# 从用户查询中提取条款编号
def extract_clause_id_from_query(query: str) -> Optional[str]:
    match = CLAUSE_ID_PATTERN.search(query)
    if match:
        return match.group(1)
    return None


# 从用户查询中提取工程对象标签
def extract_entity_tags_from_query(query: str, keywords: Optional[Dict[str, str]] = None) -> List[str]:
    kw = keywords or _get_domain_keywords()["entity_tags"]
    return [tag for keyword, tag in kw.items() if keyword in query]


# 从用户查询中提取工况/条件标签
def extract_conditions_from_query(query: str, keywords: Optional[Dict[str, str]] = None) -> List[str]:
    kw = keywords or _get_domain_keywords()["conditions"]
    return [tag for keyword, tag in kw.items() if keyword in query]


# 从用户查询中提取验算目标标签
def extract_exam_tags_from_query(query: str, keywords: Optional[Dict[str, str]] = None) -> List[str]:
    kw = keywords or _get_domain_keywords()["exam_tags"]
    return [tag for keyword, tag in kw.items() if keyword in query]


# 解析 Text-to-SQL 的作用域过滤条件。
def resolve_scope_filters(request: KnowledgeQueryRequest, doc_nodes: List[KnowledgeNode]) -> Dict[str, object]:
    return {
        "library_id": request.library_id,
        "doc_ids": [node.id for node in doc_nodes] if doc_nodes else list(request.doc_ids),
    }


# 将自然语言问题映射到当前支持的最小结构化查询对象。
def link_schema(
    query: str,
    request: KnowledgeQueryRequest,
    doc_nodes: List[KnowledgeNode],
) -> Dict[str, object]:
    normalized_query = " ".join((query or "").strip().lower().split())
    filters = resolve_scope_filters(request, doc_nodes)

    domain_kw = _get_domain_keywords()

    clause_id = extract_clause_id_from_query(query)
    standard_code_match = STANDARD_CODE_PATTERN.search(query)
    standard_code = standard_code_match.group(0) if standard_code_match else None
    entity_tags = extract_entity_tags_from_query(query, keywords=domain_kw["entity_tags"])
    conditions = extract_conditions_from_query(query, keywords=domain_kw["conditions"])
    exam_tags = extract_exam_tags_from_query(query, keywords=domain_kw["exam_tags"])

    business_filters: Dict[str, object] = {}
    if clause_id:
        business_filters["clause_id"] = clause_id
    if standard_code:
        business_filters["standard_code"] = standard_code
    if entity_tags:
        business_filters["entity_tags"] = entity_tags
    if conditions:
        business_filters["conditions"] = conditions
    if exam_tags:
        business_filters["exam_tags"] = exam_tags

    for metric_name, metric_spec in COUNT_METRIC_CATALOG.items():
        markers = metric_spec["markers"]
        if any(marker in normalized_query for marker in markers):
            return {
                "supported": True,
                "metric": metric_name,
                "table_name": metric_spec["table_name"],
                "description": metric_spec["description"],
                "filters": filters,
                "business_filters": business_filters,
            }

    if standard_code:
        return {
            "supported": True,
            "metric": "standard_lookup",
            "table_name": "canonical_documents",
            "description": "按规范编号精确查找文档",
            "filters": filters,
            "business_filters": business_filters,
        }

    if entity_tags or exam_tags or conditions or clause_id:
        return {
            "supported": True,
            "metric": "conditional_lookup",
            "table_name": "canonical_chunks",
            "description": "按业务标签条件检索规范条款",
            "filters": filters,
            "business_filters": business_filters,
        }

    if "多少" in normalized_query or "统计" in normalized_query or "汇总" in normalized_query:
        return {
            "supported": False,
            "metric": "unsupported_analytic_sql",
            "table_name": "",
            "description": "当前只支持对象计数类的最小 Text-to-SQL 闭环。",
            "filters": filters,
            "business_filters": business_filters,
            "reason": "unsupported_aggregation_pattern",
        }
    return {
        "supported": False,
        "metric": "unsupported_analytic_sql",
        "table_name": "",
        "description": "当前问题不属于最小 Text-to-SQL 支持范围。",
        "filters": filters,
        "business_filters": business_filters,
        "reason": "not_analytic_sql",
    }
