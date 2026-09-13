"""把 MinerU 原生 content_list 映射成结构层评测的块，用于"MinerU 单独 vs 我们全链"对比。

为什么不用 `mineru_raw/content_list_v2.json`：那份是**我们 step03 归一化后**的格式
（type 用 `paragraph`/`equation_interline`、内容包在 `paragraph_content` 等键里），
拿它评"MinerU 单独"会把我们自己的归一化算进去。这里读的是 MinerU 原生
`content_list.json`（`type/text/bbox/page_idx`，表格带 `table_body`），坐标是 1000 归一化。

已知的接口差异（会在报告里标注，不是 bug）：
- MinerU 原生 content_list **没有 title 类型**（标题一律 `text`），所以 GT 的 `title` 类目
  在"MinerU 单独"这一侧天然无法命中——它的 markdown 里有 `#` 级别标记，但那是 markdown 口径的事；
- 原生类型还有我们没建模的 `ref_text`（映射为 paragraph，因为参考文献列表就是正文文本）。
"""
from __future__ import annotations

import json
from pathlib import Path

from evals_core.parse_struct.jsonl_eval import PredBlock, norm_latex, norm_text

# MinerU 原生 type → 我们 block_type 词表（对齐 categories.GT_TO_OURS 的取值）
MINERU_TYPE_MAP: dict[str, str] = {
    "text": "paragraph",
    "equation": "equation_interline",
    "header": "page_header",
    "footer": "page_footer",
    "page_number": "page_number",
    "image": "image",
    "chart": "chart",
    "table": "table",
    "aside_text": "page_aside_text",
    "page_footnote": "page_footnote",
    "code": "code",
    "ref_text": "paragraph",
}

_CAPTION_KEYS = {"table": "table_caption", "image": "image_caption", "chart": "chart_caption"}
_FOOTNOTE_KEYS = {"table": "table_footnote", "image": "image_footnote", "chart": "chart_footnote"}
_CAPTION_KIND = {"table": "table_caption", "image": "figure_caption", "chart": "figure_caption"}
_FOOTNOTE_KIND = {"table": "table_footnote", "image": "figure_footnote", "chart": "figure_footnote"}


def _spans_text(value) -> str:
    """caption/footnote 字段在原生 content_list 里是数组，元素可能是字符串或 {content: ...}。"""
    if not value:
        return ""
    if isinstance(value, str):
        return norm_text(value)
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("content") or item.get("text") or ""))
        return norm_text(" ".join(parts))
    return ""


def load_mineru_blocks(content_list_path: Path) -> list[PredBlock]:
    """读 MinerU 原生 content_list → 结构层评测用的块列表（bbox 归一化到 0–1）。"""
    entries = json.loads(content_list_path.read_text(encoding="utf-8"))
    blocks: list[PredBlock] = []
    for seq, entry in enumerate(entries):
        raw_type = str(entry.get("type") or "")
        block_type = MINERU_TYPE_MAP.get(raw_type)
        if block_type is None:
            continue
        bbox = entry.get("bbox") or []
        if len(bbox) != 4:
            continue
        box = tuple(float(v) / 1000.0 for v in bbox)  # MinerU 原生坐标是 1000 归一化
        text, html, math = "", "", ""
        if raw_type == "table":
            html = str(entry.get("table_body") or "")
            text = " ".join(x for x in (_spans_text(entry.get("table_caption")), _spans_text(entry.get("table_footnote"))) if x)
        elif raw_type in ("image", "chart"):
            text = " ".join(x for x in (_spans_text(entry.get(_CAPTION_KEYS[raw_type])), _spans_text(entry.get(_FOOTNOTE_KEYS[raw_type]))) if x)
        elif raw_type == "code":
            text = norm_text(" ".join(x for x in (_spans_text(entry.get("code_caption")), str(entry.get("code_body") or "")) if x))
        elif raw_type == "equation":
            math = norm_latex(str(entry.get("text") or ""))
            text = math
        else:
            text = norm_text(str(entry.get("text") or ""))
        blocks.append(
            PredBlock(
                block_type=block_type,
                bbox=box,
                seq=seq,
                text=text,
                html=html,
                math=math,
                caption_kind=_CAPTION_KIND.get(raw_type) if text else None,
                footnote_kind=_FOOTNOTE_KIND.get(raw_type) if text else None,
            )
        )
    return blocks
