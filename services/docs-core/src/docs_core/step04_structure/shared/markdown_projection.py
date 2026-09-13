"""jsonl -> content.md 保真投影：以 jsonl 节点为唯一真相，生成可搜索/可预览的 Markdown。"""
from __future__ import annotations

from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

FURNITURE_BLOCK_TYPES = frozenset({
    "header", "footer", "page_header", "page_footer", "page_number",
})


def _node_text(node: Dict) -> str:
    return str(
        node.get("plain_text_corrected")
        or node.get("plain_text")
        or node.get("text")
        or ""
    ).strip()


def _is_furniture(node: Dict) -> bool:
    if str(node.get("layout_category") or "").lower() == "furniture":
        return True
    return str(node.get("block_type") or "").lower() in FURNITURE_BLOCK_TYPES


def _sort_nodes(nodes: List[Dict]) -> List[Dict]:
    def key(node: Dict):
        try:
            page = int(node.get("page_idx") or 0)
        except (TypeError, ValueError):
            page = 0
        try:
            seq = int(node.get("block_seq") or 0)
        except (TypeError, ValueError):
            seq = 0
        return (page, seq, str(node.get("block_uid") or node.get("id") or ""))
    return sorted(nodes, key=key)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: List[List[str]] = []
        self._current_row: Optional[List[str]] = None
        self._current_cell: Optional[List[str]] = None

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "tr":
            self._current_row = []
        elif tag in ("td", "th") and self._current_row is not None:
            self._current_cell = []

    def handle_data(self, data: str) -> None:
        if self._current_cell is not None:
            self._current_cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._current_cell is not None:
            self._current_row.append("".join(self._current_cell).strip())
            self._current_cell = None
        elif tag == "tr" and self._current_row is not None:
            self.rows.append(self._current_row)
            self._current_row = None


def _html_table_to_rows(html: str) -> List[List[str]]:
    parser = _TableParser()
    parser.feed(html)
    return parser.rows


def _render_heading(node: Dict) -> str:
    text = _node_text(node)
    if not text:
        return ""
    try:
        level = int(node.get("derived_level") or 1)
    except (TypeError, ValueError):
        level = 1
    return f"{'#' * max(1, min(6, level))} {text}"


def _render_table(node: Dict, *, html_tables: bool = False) -> str:
    html = str(
        node.get("table_html")
        or (node.get("content_json") or {}).get("html")
        or ""
    ).strip()
    # html_tables=True：直接落 HTML 表（保留 rowspan/colspan）。管道表表达不了合并单元格，
    # 拍平会让结构在交付面丢失——实测同批 200 页：管道表下表格文字 Edit_dist 0.5632，
    # MinerU（输出 HTML 表）只有 0.0488，而 jsonl 层复算仅 0.0946，差距全在投影这一步。
    # 前端本就支持后端 HTML 表（docs-ui renderTableHtmlToInlineHtml 按结构原样渲染），
    # table_lookup 也有 HTML 分支，故这条路径是回填既有能力，不是新依赖。
    if html_tables and html:
        return html
    rows = _html_table_to_rows(html)
    if not rows:
        return _node_text(node)
    lines: List[str] = []
    for index, row in enumerate(rows):
        cells = [str(c).replace("|", "\\|") for c in row]
        lines.append("| " + " | ".join(cells) + " |")
        if index == 0:
            lines.append("| " + " | ".join("---" for _ in row) + " |")
    return "\n".join(lines)


def _render_formula(node: Dict) -> str:
    body = str(node.get("formula_body") or node.get("math_content") or "").strip()
    if not body:
        return _node_text(node)
    number = str(node.get("formula_number") or "").strip()
    tag_line = f"\\tag{{{number}}}" if number else ""
    return "$$\n" + body + ("\n" + tag_line if tag_line else "") + "\n$$"


def _render_image(node: Dict) -> str:
    image_paths = node.get("image_paths") or []
    if isinstance(image_paths, list) and image_paths:
        path = str(image_paths[0])
    else:
        path = str(node.get("image_path") or "")
    if not path:
        return _node_text(node)
    alt = _node_text(node)
    return f"![{alt}]({path})"


def _render_node(node: Dict, *, html_tables: bool = False) -> str:
    block_type = str(node.get("block_type") or "").lower()
    if block_type == "title":
        return _render_heading(node)
    if block_type in ("equation_interline", "formula"):
        return _render_formula(node)
    if block_type in ("image", "figure"):
        return _render_image(node)
    if block_type == "table":
        caption = str(node.get("caption") or "").strip()
        footnote = str(node.get("footnote") or "").strip()
        parts = [caption, _render_table(node, html_tables=html_tables), footnote]
        return "\n\n".join(p for p in parts if p)
    return _node_text(node)


def build_faithful_markdown(
    nodes: List[Dict],
    build_id: str,
    *,
    include_furniture: bool = False,
    html_tables: bool = True,
) -> Tuple[str, Dict[str, Dict[str, int]]]:
    """返回 (md_text, line_ranges)；line_ranges 为 block_uid -> {start, end}，1 起始、含 build_id 头行。"""
    lines: List[str] = [f"<!-- build_id: {build_id} -->"]
    line_ranges: Dict[str, Dict[str, int]] = {}
    for node in _sort_nodes(nodes):
        if int(node.get("is_active", 1) or 0) == 0:
            continue
        if not include_furniture and _is_furniture(node):
            continue
        text = _render_node(node, html_tables=html_tables)
        if not text:
            continue
        uid = str(node.get("block_uid") or node.get("id") or "").strip()
        start = len(lines) + 1
        lines.extend(text.splitlines())
        end = len(lines)
        if uid:
            line_ranges[uid] = {"start": start, "end": end}
        lines.append("")
    return "\n".join(lines) + "\n", line_ranges
