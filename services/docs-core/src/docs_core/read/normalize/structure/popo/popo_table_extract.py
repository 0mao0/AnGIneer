"""PoPo 表格内容通道（G1，阶段一前置）。

把 enriched_blocks.json 中 ``type=="table"`` 块的 ``content``（完整 ``<table>...</table>``
HTML，跨页合并后内容）解析为行列，喂给 CanonicalBlock.table_html /
CanonicalTable。原始 HTML 只进 ``table_html`` 旁路字段，不流进 content/table_summary
chunk 污染 FTS。
"""
from html.parser import HTMLParser
import re
from typing import Any, Dict, List, Optional


def clean_table_text(value: Any) -> str:
    """归一化单元格文本。"""
    return re.sub(r"\s+", " ", str(value or "")).strip()


class _TableHTMLParser(HTMLParser):
    """解析 ``<table>`` 为二维数组；按 colspan 展开重复单元格。"""

    def __init__(self) -> None:
        super().__init__()
        self.rows: List[List[str]] = []
        self._row: Optional[List[str]] = None
        self._cell_parts: Optional[List[str]] = None
        self._cell_colspan = 1

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag == "tr":
            self._row = []
            return
        if tag in {"td", "th"}:
            self._cell_parts = []
            attr_map = dict(attrs)
            try:
                self._cell_colspan = max(1, int(attr_map.get("colspan", "1") or "1"))
            except (TypeError, ValueError):
                self._cell_colspan = 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            text = clean_table_text("".join(self._cell_parts))
            self._row.extend([text] * self._cell_colspan)
            self._cell_parts = None
            return
        if tag == "tr" and self._row is not None:
            if any(cell for cell in self._row):
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)


# 解析 HTML 表格为二维数组（独立可复用；builder 的 SimpleHtmlTableParser 为其前身）。
def parse_table_html(table_html: str) -> List[List[str]]:
    parser = _TableHTMLParser()
    parser.feed(table_html or "")
    return [row for row in parser.rows if any(cell for cell in row)]


# 从 enriched block 中提取原始表格 HTML；非 HTML 的 content 返回 None（视为已 textified）。
def extract_table_html(block: Dict[str, Any]) -> Optional[str]:
    if not isinstance(block, dict):
        return None
    content = block.get("content")
    if isinstance(content, dict):
        content = content.get("html") or content.get("table_html") or ""
    text = str(content or "").strip()
    if "<table" in text.lower():
        return text
    return None


# 把表格 HTML 转为 textified 单段文本（行内 "|" 分隔、行间换行）。
def textify_table_html(table_html: str) -> str:
    rows = parse_table_html(table_html)
    return "\n".join(
        " | ".join(cell for cell in row if cell)
        for row in rows
        if any(cell for cell in row)
    )
