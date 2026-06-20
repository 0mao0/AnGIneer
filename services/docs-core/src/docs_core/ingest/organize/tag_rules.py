"""从文档内容与路径推断检索标签的规则集。"""

_RULE_MAP = {
    "强制性条文": ["必须", "严禁", "不得", "应"],
    "抗震": ["抗震"],
    "换算": ["换算"],
    "公式": ["公式", "式中", "按式"],
    "表格": ["表", "表格"],
}


def infer_entity_tags(text: str, section_path: str = "") -> list[str]:
    """从文本内容推断实体标签。"""
    combined = f"{section_path}\n{text}"
    tags: list[str] = []
    for tag, keywords in _RULE_MAP.items():
        if any(kw in combined for kw in keywords):
            tags.append(tag)
    return tags


def infer_conditions(text: str, section_path: str = "") -> list[str]:
    """从文本内容推断条件标签（条文属性）。"""
    combined = f"{section_path}\n{text}"
    if any(kw in combined for kw in ["必须", "严禁", "不得", "应"]):
        return ["强制性条文"]
    return []
