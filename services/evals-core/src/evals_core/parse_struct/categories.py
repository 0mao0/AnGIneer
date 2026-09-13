"""OmniDocBench GT 类目 ↔ 本仓库 pipeline block_type 的映射。

用途：结构层评测（scripts/eval_parse_struct.py）把 GT 标注的块与
`doc_blocks_graph.jsonl` 的块按几何位置对齐后，需要一张表回答"GT 的这类东西，
对应我们的哪类块"。

设计取舍（2026-09-12 与 GT/pipeline 双边词表逐项对照后确定）：
- 我们侧没有独立的 caption / footnote 块类型——caption 是 `paragraph` 块，靠父节点的
  `caption_block_uid(s)` 指针挂靠；footnote 同理（`footnote_block_uid(s)`）。因此这两类
  不能按 block_type 映射，改为按"被谁引用"映射（见 CAPTION_KIND / FOOTNOTE_KIND）。
- GT 的 figure 对应我们 image + chart 两个类型（我们拆得更细）。
- GT 独有的 abandon / text_mask / *_mask / equation_semantic / equation_explanation /
  reference 等，我们无对应概念，不进分母（见 UNMAPPED_GT）。
"""

# GT 类目 → 我们可作候选的 block_type 集合
GT_TO_OURS: dict[str, set[str]] = {
    "text_block": {"paragraph"},
    "title": {"title"},
    "header": {"page_header"},
    "footer": {"page_footer"},
    "page_number": {"page_number"},
    "page_footnote": {"page_footnote"},
    "equation_isolated": {"equation_interline"},
    "table": {"table"},
    "figure": {"image", "chart"},
    "code_txt": {"code"},
    "list_group": {"list"},
}

# 靠"被引用关系"而非 block_type 识别的 GT 类目：值为 (引用的父块类型, 关系)
CAPTION_KIND: dict[str, tuple[set[str], str]] = {
    "table_caption": ({"table"}, "caption"),
    "figure_caption": ({"image", "chart"}, "caption"),
    "table_footnote": ({"table"}, "footnote"),
    "figure_footnote": ({"image", "chart"}, "footnote"),
}

# 我们侧存在但 GT 无对应（或语义不等价）的 block_type，仅统计不评分
UNMAPPED_OURS: set[str] = {"page_aside_text", "algorithm"}

# GT 侧存在但我们无对应概念的类目，不进分母
UNMAPPED_GT: set[str] = {
    "abandon",
    "text_mask",
    "organic_chemical_formula_mask",
    "equation_semantic",
    "equation_explanation",
    "equation_caption",
    "reference",
}

# GT 类别 → 判定"类目是否正确"时使用的展示名（用于报表列）
CATEGORY_LABEL: dict[str, str] = {k: k for k in GT_TO_OURS} | {k: k for k in CAPTION_KIND}


def ours_types_for(gt_category: str) -> set[str]:
    """GT 类目可接受的我们的 block_type 集合；caption/footnote 返回空（走指针映射）。"""
    return GT_TO_OURS.get(gt_category, set())


def is_scored(gt_category: str) -> bool:
    """该 GT 类目是否进评测分母。"""
    return gt_category in GT_TO_OURS or gt_category in CAPTION_KIND
