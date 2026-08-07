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
    ordered: List[Dict[str, Any]],
    page: int,
    block_seq: int,
    table_bbox=None,
) -> bool:
    """目标页上是否存在续表标记（目标表之前，或位于目标表上方的表头块）。"""
    table_y0 = 1.0
    if isinstance(table_bbox, (list, tuple)) and len(table_bbox) >= 4:
        table_y0 = float(table_bbox[1])
    for node in ordered:
        if int(node.get("page_idx") or 0) != page:
            continue
        if node.get("block_type") not in (
            "title", "paragraph", "text", "list_item", "page_header", "header"
        ):
            continue
        if not CONTINUATION_MARKER_RE.search(str(node.get("plain_text") or "")):
            continue
        if int(node.get("block_seq") or 0) < block_seq:
            return True
        bbox = node.get("bbox")
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            if float(bbox[1]) < table_y0:
                return True
    return False


_ATTACHMENT_CANDIDATE_TYPES = frozenset({
    "paragraph", "text", "list", "list_item", "title", "page_header", "header",
})
_MAX_ATTACHMENT_TEXT_LEN = 40
_TOP_BAND_Y = 0.25


def _compact_text(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def _page_table_number(
    nodes: List[Dict[str, Any]], page: int, *, exclude_uid: Optional[str] = None
) -> Optional[str]:
    """在该页短文本块中找表号（如页眉“表 D.6.2-4”），用于 caption 缺失时定表组。"""
    for node in nodes:
        if exclude_uid and _uid(node) == exclude_uid:
            continue
        if int(node.get("page_idx") or 0) != page:
            continue
        if node.get("block_type") == "table":
            continue
        text = _compact_text(node.get("plain_text"))
        if not (2 <= len(text) <= _MAX_ATTACHMENT_TEXT_LEN):
            continue
        number = _extract_table_number(text)
        if number:
            return number
    return None


def attach_table_continuation_headers(
    nodes: List[Dict[str, Any]],
    fragment_page_by_uid: Dict[str, int],
    head_fragment_pages: Optional[Dict[str, List[int]]] = None,
) -> int:
    """把跨页合并表的续页表头块标记为 attachment，并挂到首表 caption 附件。

    判定不依赖“续表”字样：续页顶部、短文本、且包含该表组表号的块都算附件；
    附件仍保留在 jsonl（含 bbox），但展示层隐藏、语义层排除。
    """
    changed = 0
    for head in nodes:
        if head.get("block_type") != "table":
            continue
        merged_from = head.get("merged_from") or []
        head_uid = _uid(head)
        pages = (
            list(head_fragment_pages.get(head_uid, []))
            if head_fragment_pages
            else []
        )
        if not pages and merged_from:
            pages = [
                int(fragment_page_by_uid.get(str(uid), -1))
                for uid in merged_from
            ]
        if not pages:
            continue
        number = _extract_table_number(_caption_text(head))
        if not number:
            number = _page_table_number(
                nodes, int(head.get("page_idx") or 0), exclude_uid=head_uid
            )
        if not number:
            for page in pages:
                if page < 0:
                    continue
                number = _page_table_number(nodes, page)
                if number:
                    break
        if not number:
            continue
        for page in pages:
            if page < 0:
                continue
            for cand in nodes:
                if _uid(cand) == head_uid:
                    continue
                if int(cand.get("page_idx") or 0) != page:
                    continue
                if cand.get("block_type") == "table":
                    continue
                if str(cand.get("block_type") or "").lower() not in _ATTACHMENT_CANDIDATE_TYPES:
                    continue
                if str(cand.get("layout_category") or "").lower() == "furniture":
                    continue
                text = _compact_text(cand.get("plain_text"))
                if not (2 <= len(text) <= _MAX_ATTACHMENT_TEXT_LEN):
                    continue
                if number not in text:
                    continue
                bbox = cand.get("bbox")
                y0 = float(bbox[1]) if isinstance(bbox, (list, tuple)) and len(bbox) >= 4 else 1.0
                if y0 > _TOP_BAND_Y:
                    continue
                if cand.get("layout_category") == "attachment":
                    continue
                cand["layout_category"] = "attachment"
                uids = head.get("caption_block_uids")
                if not isinstance(uids, list):
                    uids = []
                    head["caption_block_uids"] = uids
                if _uid(cand) not in uids:
                    uids.append(_uid(cand))
                changed += 1
    return changed


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
            tgt.get("bbox"),
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


__all__ = [
    "detect_table_continuations",
    "attach_table_continuation_headers",
    "CONTINUATION_MARKER_RE",
]
