"""PoPo 跨页续排表启发式检测（Task B）：为 PoPo 预筛漏掉的续表生成 table_merge 指令。

覆盖两类真实场景（PoPo 预筛 `text_between_tables` 拒绝）：
- 续表标记组：下一页首表之前有 "续表A.0.2-2" 文本块；
- LNG 表中段：页首游离文本（"10"/"0"）同样触发 text_between_tables 拒绝。

配对顺序：上一页末表 → 下一页首表（相邻页）；至少两条证据（续表标记 / 表头相似 /
列数一致 / bbox 宽度比<10%）同时满足才合并；caption 编号不同不合并；中间无 title。
"""

import re
from typing import Any, Dict, List, Optional

from docs_core.step04_structure.shared.table_html_utils import parse_table_html

CONTINUATION_MARKER_RE = re.compile(
    r"续表|续前|续上|续\s*表|continued|\(续\)",
    re.IGNORECASE,
)

# 至少两条证据同时满足才合并（防误并）
MIN_EVIDENCE = 2
HEADER_COMPARE_ROWS = 2


def _uid(node: Dict[str, Any]) -> str:
    return str(node.get("block_uid") or node.get("id") or "").strip()


def _sort_key(node: Dict[str, Any]) -> tuple[int, int]:
    return (int(node.get("page_idx") or 0), int(node.get("block_seq") or 0))


def _rows_of(node: Dict[str, Any]) -> List[List[str]]:
    html = str(node.get("table_html") or "")
    if not html:
        return []
    rows = parse_table_html(html)
    return [[str(cell) for cell in row] for row in rows]


def _norm_cells(row: List[str]) -> List[str]:
    return [re.sub(r"\s+", "", str(cell)) for cell in row]


def _caption_text(node: Dict[str, Any]) -> str:
    caption = str(node.get("caption") or "").strip()
    if caption:
        return caption
    cj = node.get("content_json") if isinstance(node.get("content_json"), dict) else {}
    items = cj.get("table_caption") or []
    if isinstance(items, str):
        return items.strip()
    texts: List[str] = []
    for item in items:
        if isinstance(item, dict):
            texts.append(str(item.get("content") or ""))
        else:
            texts.append(str(item))
    return "".join(texts).strip()


def _extract_table_number(caption: str) -> Optional[str]:
    match = re.search(
        r"(?:表|table|exhibit)\s*([A-Za-z]?[\d.]+(?:-\d+)?)",
        caption,
        re.IGNORECASE,
    )
    if not match:
        return None
    return re.sub(r"\s", "", match.group(1)).upper()


def _caption_numbers_conflict(src: Dict[str, Any], tgt: Dict[str, Any]) -> bool:
    num1 = _extract_table_number(_caption_text(src))
    num2 = _extract_table_number(_caption_text(tgt))
    return bool(num1 and num2 and num1 != num2)


def _header_match(src: Dict[str, Any], tgt: Dict[str, Any]) -> bool:
    src_rows = _rows_of(src)
    tgt_rows = _rows_of(tgt)
    if not src_rows or not tgt_rows:
        return False
    for n in range(1, HEADER_COMPARE_ROWS + 1):
        if n <= len(src_rows) and n <= len(tgt_rows):
            if _norm_cells(src_rows[:n]) == _norm_cells(tgt_rows[:n]):
                return True
    return False


def _column_count(rows: List[List[str]]) -> int:
    return max((len(row) for row in rows), default=0)


def _width_ok(src: Dict[str, Any], tgt: Dict[str, Any]) -> bool:
    bbox1 = src.get("bbox")
    bbox2 = tgt.get("bbox")
    if not isinstance(bbox1, (list, tuple)) or len(bbox1) < 4:
        return False
    if not isinstance(bbox2, (list, tuple)) or len(bbox2) < 4:
        return False
    w1 = float(bbox1[2]) - float(bbox1[0])
    w2 = float(bbox2[2]) - float(bbox2[0])
    if min(w1, w2) <= 0:
        return False
    return abs(w1 - w2) / min(w1, w2) < 0.10


def _continuation_marker_before(
    ordered: List[Dict[str, Any]], page: int, block_seq: int
) -> bool:
    """目标表之前、同页内最近的 text/标题块是否含续表标记。"""
    for node in ordered:
        if int(node.get("page_idx") or 0) != page:
            continue
        if int(node.get("block_seq") or 0) >= block_seq:
            break
        if node.get("block_type") in ("title", "paragraph", "text", "list_item"):
            if CONTINUATION_MARKER_RE.search(str(node.get("plain_text") or "")):
                return True
    return False


def detect_table_continuations(
    nodes: List[Dict[str, Any]], *, doc_id: str
) -> List[Dict[str, Any]]:
    """启发式检测跨页续排表，返回 [{kind: "table_merge", source_uid, target_uid}]。"""
    ordered = sorted(nodes, key=_sort_key)
    tables_by_page: Dict[int, List[Dict[str, Any]]] = {}
    for node in ordered:
        if node.get("block_type") == "table":
            tables_by_page.setdefault(int(node.get("page_idx") or 0), []).append(node)

    pages = sorted(tables_by_page)
    instructions: List[Dict[str, Any]] = []
    for p_idx in range(len(pages) - 1):
        page1, page2 = pages[p_idx], pages[p_idx + 1]
        if page2 != page1 + 1:
            continue
        src = tables_by_page[page1][-1]
        tgt = tables_by_page[page2][0]

        if _caption_numbers_conflict(src, tgt):
            continue

        src_key = _sort_key(src)
        tgt_key = _sort_key(tgt)
        title_between = any(
            _sort_key(node) > src_key and _sort_key(node) < tgt_key
            and node.get("block_type") == "title"
            for node in ordered
        )
        if title_between:
            continue

        src_rows = _rows_of(src)
        tgt_rows = _rows_of(tgt)
        col_match = (
            _column_count(src_rows) == _column_count(tgt_rows)
            and _column_count(src_rows) > 0
        )
        width_ok = _width_ok(src, tgt)
        marker = _continuation_marker_before(
            ordered,
            int(tgt.get("page_idx") or 0),
            int(tgt.get("block_seq") or 0),
        )
        header = _header_match(src, tgt)

        evidence = int(marker) + int(header) + int(col_match) + int(width_ok)
        if evidence < MIN_EVIDENCE:
            continue

        instructions.append({
            "kind": "table_merge",
            "source_uid": _uid(src),
            "target_uid": _uid(tgt),
        })
    return instructions


__all__ = ["detect_table_continuations", "CONTINUATION_MARKER_RE"]
