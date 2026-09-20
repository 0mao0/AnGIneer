"""表格题注解析（单一真相源）：续表启发式与 PoPo 指令校验共用。

核心判据：**两侧都能取到题注编号且编号不同 → 不是同一张表，不得合并**。
"列数一致"只能确认、不能否定——同构异表（如仿真结果表 S1..S5，列数天然相同）
在这条判据上永远成立，所以它必须与编号判据配对使用（2026-09-20 实踩：
PoPo 把 Table S1..S5 判成一条续表链，行数据被拼成一张、被吞表的表号题注
从 plain_text/summary 消失，按表号检索失锚——引用侧从"答对且表级引用正确"
变成"答不出、或命中别篇文档的同名表"）。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional, Tuple

# 题注编号：表/Table/Tab.、图/Figure/Fig.、Exhibit（中英文题注通用）。
# `续表 D.0.2-3` 同样命中（"表" 关键字 + 编号）。
_TABLE_NUMBER_RE = re.compile(
    r"(?:表|table|tab\.?|exhibit|figure|fig\.?)\s*([A-Za-z]?[\d.]+(?:-\d+)?)",
    re.IGNORECASE,
)


def caption_text(node: Dict[str, Any]) -> str:
    """该表格块的题注文本：``caption`` 字段 → ``content_json.table_caption`` → 空串。"""
    caption = str(node.get("caption") or "").strip()
    if caption:
        return caption
    content_json = node.get("content_json") if isinstance(node.get("content_json"), dict) else {}
    items = content_json.get("table_caption") or []
    if isinstance(items, str):
        return items.strip()
    texts = []
    for item in items:
        if isinstance(item, dict):
            texts.append(str(item.get("content") or ""))
        else:
            texts.append(str(item))
    return "".join(texts).strip()


def extract_table_number(caption: str) -> Optional[str]:
    """从题注中取编号（大写、去空格、去尾部句点），取不到返回 None。

    尾部句点必须去掉：`FIG. A.6. Values of ...` 的编号是 `A.6`，
    `[\\d.]+` 会把题注句末的 `.` 一起吃掉。
    """
    match = _TABLE_NUMBER_RE.search(str(caption or ""))
    if not match:
        return None
    return re.sub(r"\s", "", match.group(1)).rstrip(".").upper()


def caption_numbers(source: Dict[str, Any], target: Dict[str, Any]) -> Tuple[Optional[str], Optional[str]]:
    """两侧的题注编号（取不到为 None），供拒绝原因与日志复用。"""
    return extract_table_number(caption_text(source)), extract_table_number(caption_text(target))


def caption_numbers_conflict(source: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """两侧题注编号都存在且不同 → True（判非续表）。

    单侧缺编号不判冲突：续页表常见"无题注"或"续表 X"重复同号，
    真正的新表则两侧各有独立编号。
    """
    source_number, target_number = caption_numbers(source, target)
    return bool(source_number and target_number and source_number != target_number)
