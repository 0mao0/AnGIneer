"""结构层解析评测：直接拿 `doc_blocks_graph.jsonl` 与 OmniDocBench GT 标注对齐打分。

与官方 markdown 口径（scripts/run_omnidocbench_eval.py 调官方镜像）的区别：
官方口径把我们的 content.md 交给评测器，由**对方的正则**再切块，位置是 markdown 字符偏移；
本模块不绕 markdown，用我们块的真实 bbox 与 GT 的 poly 做**几何对齐**，量的正是 RAG 检索
依赖的那一层（块类目/文本/表格结构/阅读顺序）。理由与盲区见 docs/parse-structure-eval.md。

指标（全部基于几何匹配，不依赖任何外部评测器）：
- 检测召回/精确率：按类目统计 GT 块被覆盖比例、我们块被用掉的比例
- 块文本保真：匹配上的块做归一化编辑距离（Levenshtein）
- 表格结构：TEDS（官方实现，HTML↔HTML，vendor 在 _vendor/omnidocbench）
- 公式：LaTeX 串归一化编辑距离
- 阅读顺序：相邻对顺序正确率 + Kendall tau

注意：这是**我们自定义的口径**，用于内部回归跟踪（同规则前后可比），不可声称是
OmniDocBench 官方分数（官方分数只从 markdown 口径来）。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from evals_core.parse_eval.categories import (
    CAPTION_KIND,
    UNMAPPED_OURS,
    is_scored,
    ours_types_for,
)

try:  # 编辑距离：装了 Levenshtein 用 C 实现，否则退化到 difflib 近似
    import Levenshtein

    def _edit_distance(a: str, b: str) -> int:
        return Levenshtein.distance(a, b)

except ImportError:  # pragma: no cover
    import difflib

    def _edit_distance(a: str, b: str) -> int:
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        return sum(max(i2 - i1, j2 - j1) for tag, i1, i2, j1, j2 in sm.get_opcodes() if tag != "equal")


_WS = re.compile(r"[ \t\u3000]+")
_MD_HEAD = re.compile(r"^#+\s*")
_ENV_WRAP = re.compile(r"\\(begin|end)\{[^}]*\}")

# caption 匹配的宽容参数：caption 文本通常贴在表/图外侧，我们多数情况下没有它的独立 bbox
CAPTION_MATCH_MARGIN = 0.06   # 页面归一化尺寸的 6%
CAPTION_IOU_MIN = 0.05



def norm_text(value: str | None) -> str:
    """评测用文本归一：去首尾空白、合并连续空白/换行、去 GT 标题里的 markdown # 前缀。

    GT 的 title.text 形如 `### 4.6 Exploration SDP`（标注自带 markdown 井号），
    我们的 plain_text 不含井号——不剥掉会把标题类目整体算成错。
    """
    text = (value or "").replace("\r", "\n")
    text = re.sub(r"\s*\n\s*", " ", text)
    text = _WS.sub(" ", text).strip()
    return _MD_HEAD.sub("", text)


_LEFT_RIGHT = re.compile(r"\\(?:left|right|bigl|bigr|Bigl|Bigr|biggl|biggr|Biggl|Biggr)\s*")
_HSPACE_CMD = re.compile(r"\\(?:quad|qquad|thinspace|enspace|medspace|thickspace|,|;|!|:)")
_CMD_SPACE = re.compile(r"(\\(?:text|mathrm|mathbf|mathit|mathsf|mathtt|operatorname|begin|end))\s*\{")
_LATEX_ESCAPES = (("\\_", "_"), ("\\%", "%"), ("\\&", "&"), ("\\#", "#"), ("\\$", "$"))


def norm_latex(value: str | None) -> str:
    """公式归一，供**串比对**用（不是 CDM 的口径）。

    同一份公式，不同 OCR 引擎的 LaTeX 序列化风格差异极大——实测 GT `{2DV}` / 我们 `2 D V`、
    GT `\\text{Params}` / 我们 `\\text {Params}`、GT `d_{w}` / 我们 `d _ {w}`。直接比字符串
    会把这些**格式差异**算成识别错误（实测裸比相似度仅 0.35）。故这里做去风格化处理：
    去包裹（$$ / \\[ \\] / equation 环境）、去全部空白、\\left/\\right 还原、间距命令删除、
    转义还原、最后去掉花括号（`{2DV}` 与 `2DV` 视为同）。

    这是**结构不敏感**的近似——官方口径是 CDM（渲染成图再比像素），本指标只用于内部回归跟踪。
    """
    text = (value or "").strip()
    text = re.sub(r"^\$\$?", "", text)
    text = re.sub(r"\$\$?$", "", text)
    text = re.sub(r"^\\\[", "", text)
    text = re.sub(r"\\\]$", "", text)
    text = _ENV_WRAP.sub(" ", text)
    text = _LEFT_RIGHT.sub("", text)
    text = _CMD_SPACE.sub(r"\1{", text)
    text = _HSPACE_CMD.sub("", text)
    text = text.replace("\\pmod", "\\mod")
    for src, dst in _LATEX_ESCAPES:
        text = text.replace(src, dst)
    text = re.sub(r"\s+", "", text)
    return text.replace("{", "").replace("}", "")


def poly_to_bbox(poly: list[float] | None) -> tuple[float, float, float, float] | None:
    """GT 的 poly 是扁平列表 [x1,y1,x2,y2,...]，转成 (x0,y0,x1,y1)。"""
    if not poly or len(poly) < 4:
        return None
    xs, ys = poly[0::2], poly[1::2]
    return (min(xs), min(ys), max(xs), max(ys))


def norm_bbox(box: tuple[float, float, float, float], width: float, height: float) -> tuple[float, float, float, float]:
    """把像素/页面坐标系的 bbox 归一化到 0–1（我们的 bbox 本来就是归一化的，直接传 1.0）。"""
    w = width or 1.0
    h = height or 1.0
    return (box[0] / w, box[1] / h, box[2] / w, box[3] / h)


def iou(a: tuple, b: tuple) -> float:
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    if inter <= 0:
        return 0.0
    area_a = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    area_b = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def center_inside(inner: tuple, outer: tuple, margin: float = 0.0) -> bool:
    cx, cy = (inner[0] + inner[2]) / 2, (inner[1] + inner[3]) / 2
    return (outer[0] - margin) <= cx <= (outer[2] + margin) and (outer[1] - margin) <= cy <= (outer[3] + margin)


@dataclass
class GtBlock:
    category: str
    bbox: tuple | None      # 归一化
    order: int | None
    text: str               # text / latex 归一后
    html: str               # 表格用
    is_table: bool = False


@dataclass
class PredBlock:
    block_type: str
    bbox: tuple             # 归一化
    seq: int
    text: str
    html: str = ""
    math: str = ""
    caption_kind: str | None = None    # 'table_caption' / 'figure_caption'
    footnote_kind: str | None = None   # 'table_footnote' / 'figure_footnote'


def load_gt_page(sample: dict) -> tuple[str, list[GtBlock]]:
    """从 OmniDocBench 的一条 GT 样本解析出页 id 与待评块列表。"""
    info = sample.get("page_info") or {}
    page_id = Path(str(info.get("image_path") or "")).name
    width, height = float(info.get("width") or 1), float(info.get("height") or 1)
    blocks: list[GtBlock] = []
    for det in sample.get("layout_dets") or []:
        category = str(det.get("category_type") or "")
        if det.get("ignore") or not is_scored(category):
            continue
        box = poly_to_bbox(det.get("poly"))
        is_table = category == "table"
        text = norm_latex(det.get("latex")) if category == "equation_isolated" else norm_text(det.get("text"))
        blocks.append(
            GtBlock(
                category=category,
                bbox=norm_bbox(box, width, height) if box else None,
                order=det.get("order"),
                text=text,
                html=str(det.get("html") or "") if is_table else "",
                is_table=is_table,
            )
        )
    return page_id, blocks


def load_pred_blocks(jsonl_path: Path) -> list[PredBlock]:
    """读一篇文档的 doc_blocks_graph.jsonl，并把 caption/footnote 的挂靠关系解析出来。"""
    nodes = [json.loads(line) for line in jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    by_uid = {str(n.get("block_uid")): n for n in nodes}

    # 父块类型 → 关系名，决定被引用块算作哪一类 caption/footnote
    kind_of_parent = {}
    for node in nodes:
        parent_type = str(node.get("block_type") or "")
        for kind, (parents, rel) in CAPTION_KIND.items():
            if parent_type in parents:
                kind_of_parent.setdefault(str(node.get("block_uid")), {})[rel] = kind

    caption_of: dict[str, str] = {}
    footnote_of: dict[str, str] = {}
    for uid, rels in kind_of_parent.items():
        node = by_uid.get(uid) or {}
        for target_key, rel in (("caption_block_uid", "caption"), ("footnote_block_uid", "footnote")):
            target = node.get(target_key)
            if target:
                (caption_of if rel == "caption" else footnote_of)[str(target)] = rels[rel]
        for target_key, rel in (("caption_block_uids", "caption"), ("footnote_block_uids", "footnote")):
            for target in node.get(target_key) or []:
                (caption_of if rel == "caption" else footnote_of)[str(target)] = rels[rel]

    blocks: list[PredBlock] = []
    for node in nodes:
        bbox = node.get("bbox")
        if not bbox or len(bbox) != 4:
            continue
        uid = str(node.get("block_uid"))
        box = (float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
        blocks.append(
            PredBlock(
                block_type=str(node.get("block_type") or ""),
                bbox=box,
                seq=int(node.get("block_seq") or 0),
                text=norm_text(node.get("plain_text")),
                html=str(node.get("table_html") or ""),
                math=norm_latex(node.get("math_content") or node.get("formula_body")),
                caption_kind=caption_of.get(uid),
                footnote_kind=footnote_of.get(uid),
            )
        )
        # 表/图的 caption 多数不落成独立块（实测 200 篇：250 个表图节点里只有 15 个带指针块，
        # 但有 50 个把 caption 文本挂在父节点字段上）。这里把该文本合成一个"锚在父块位置上"的
        # caption 候选，否则这类 caption 一律记成漏检（假差）。
        parent_type = str(node.get("block_type") or "")
        for text_key, kind_suffix, kind_map in (
            ("caption", "caption", {"table": "table_caption", "image": "figure_caption", "chart": "figure_caption"}),
            ("footnote", "footnote", {"table": "table_footnote", "image": "figure_footnote", "chart": "figure_footnote"}),
        ):
            text = norm_text(node.get(text_key))
            if not text or parent_type not in kind_map:
                continue
            if (kind_suffix == "caption" and uid in caption_of) or (kind_suffix == "footnote" and uid in footnote_of):
                continue
            blocks.append(
                PredBlock(
                    block_type=parent_type,
                    bbox=box,
                    seq=int(node.get("block_seq") or 0),
                    text=text,
                    caption_kind=kind_map[parent_type] if kind_suffix == "caption" else None,
                    footnote_kind=kind_map[parent_type] if kind_suffix == "footnote" else None,
                )
            )
    return blocks


def covered_ratio(gt_box: tuple, pred_box: tuple) -> float:
    """GT 框被预测框覆盖的面积比例（用于跨粒度匹配，见 _candidates 的说明）。"""
    ix0, iy0 = max(gt_box[0], pred_box[0]), max(gt_box[1], pred_box[1])
    ix1, iy1 = min(gt_box[2], pred_box[2]), min(gt_box[3], pred_box[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    gt_area = max(0.0, gt_box[2] - gt_box[0]) * max(0.0, gt_box[3] - gt_box[1])
    return inter / gt_area if gt_area > 0 else 0.0


def _candidates(gt: GtBlock, preds: list[PredBlock], iou_min: float, cover_min: float) -> list[PredBlock]:
    """一个 GT 块的候选预测块：类目匹配（或指针匹配）且位置重叠。

    三条并集规则，缺一不可——块粒度两边不一致是常态：
    1. IoU ≥ iou_min：位置基本重合；
    2. 预测块中心落在 GT 框内：我们的块比 GT 块小/居中（如 GT 一个 text_block 被我们切成多段）；
    3. GT 框被预测块覆盖 ≥ cover_min：我们的块比 GT 块大（如实测 2026-09-12：GT 把公式数组
       按行标成 7 个 equation_isolated，我们合成 1 个 equation_interline——只靠前两条会全记漏检）。

    caption/footnote 另给宽容边距：caption 通常贴在表/图外面（上/下方），而我们的 caption
    候选锚在表图自己的 bbox 上，不加边距必然匹配不上（实测 200 篇 caption 召回会掉成 0%）。
    """
    is_caption = gt.category in CAPTION_KIND
    margin = CAPTION_MATCH_MARGIN if is_caption else 0.01
    out = []
    for pred in preds:
        if is_caption:
            rel = CAPTION_KIND[gt.category][1]
            kind = pred.caption_kind if rel == "caption" else pred.footnote_kind
            if kind != gt.category:
                continue
        elif pred.block_type not in ours_types_for(gt.category):
            continue
        if gt.bbox is None:
            continue
        if (
            iou(gt.bbox, pred.bbox) >= (CAPTION_IOU_MIN if is_caption else iou_min)
            or center_inside(pred.bbox, gt.bbox, margin=margin)
            or center_inside(gt.bbox, pred.bbox, margin=margin)
            or covered_ratio(gt.bbox, pred.bbox) >= cover_min
        ):
            out.append(pred)
    return out


def _area(box: tuple) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _kendall_tau(pairs: list[tuple[int, int]]) -> float | None:
    """pairs = [(GT 顺序, 我们的顺序)]，返回 Kendall tau（1 完全一致，-1 完全颠倒）。"""
    n = len(pairs)
    if n < 2:
        return None
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            dx = pairs[i][0] - pairs[j][0]
            dy = pairs[i][1] - pairs[j][1]
            if dx == 0 or dy == 0:
                continue
            if (dx > 0) == (dy > 0):
                conc += 1
            else:
                disc += 1
    total = conc + disc
    return (conc - disc) / total if total else None


def eval_page(gt_blocks: list[GtBlock], preds: list[PredBlock], iou_min: float = 0.3, cover_min: float = 0.6) -> dict:
    """单页评测：命中/顺序按 GT 块计，文本与公式按**覆盖分组**计。

    为什么要分组：两边的块粒度经常不一致——实测 2026-09-12 某页 GT 把公式数组按行标成
    7 个 equation_isolated，我们合成 1 个块。若逐 GT 块比较，就是"整段 vs 单行"×7，
    相似度全近 0，把公式指标压到 0.07（假差）。正确做法是把互相覆盖的 GT 块归为一组，
    组内两侧各自拼接后再比一次。
    """
    used: set[int] = set()
    rows = []
    per_gt_cands: list[list[PredBlock]] = []
    for gt in gt_blocks:
        cands = _candidates(gt, preds, iou_min, cover_min)
        for c in cands:
            used.add(id(c))
        cands_sorted = sorted(cands, key=lambda p: p.seq)
        rep_seq = cands_sorted[0].seq if cands_sorted else None
        teds_cand = None
        if cands and gt.category == "table":
            teds_cand = max(cands, key=lambda p: iou(gt.bbox, p.bbox))
        per_gt_cands.append(cands_sorted)
        rows.append(
            {
                "gt": gt,
                "cands": len(cands),
                "rep_seq": rep_seq,
                "teds_cand": teds_cand,
            }
        )

    order_pairs = [(r["gt"].order, r["rep_seq"]) for r in rows if r["gt"].order is not None and r["rep_seq"] is not None]
    order_pairs.sort()
    adj_ok = adj_n = 0
    for i in range(len(order_pairs) - 1):
        adj_n += 1
        if order_pairs[i][1] <= order_pairs[i + 1][1]:
            adj_ok += 1
    return {
        "rows": rows,
        "groups": _build_groups(gt_blocks, per_gt_cands),
        "used": used,
        "order_tau": _kendall_tau(order_pairs),
        "order_adjacent": (adj_ok / adj_n) if adj_n else None,
        "order_adjacent_n": adj_n,
    }


def _build_groups(gt_blocks: list[GtBlock], per_gt_cands: list[list[PredBlock]]) -> list[dict]:
    """把被同一个预测块覆盖的 GT 块并成一组（并查集），组内两侧分别拼接文本。

    只对"文本型"类目分组：表格（TEDS 按表 HTML 比）与图（不评文本）逐块处理。
    """
    n = len(gt_blocks)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[rj] = ri

    for pred_id in {id(p) for cands in per_gt_cands for p in cands}:
        covered = [i for i, cands in enumerate(per_gt_cands) if any(id(p) == pred_id for p in cands)]
        covering = [i for i in covered if gt_blocks[i].category not in ("table", "figure")]
        for i in covering[1:]:
            union(covering[0], i)

    groups: dict[int, list[int]] = {}
    for i in range(n):
        if gt_blocks[i].category in ("table", "figure"):
            continue
        groups.setdefault(find(i), []).append(i)

    out = []
    for members in groups.values():
        members.sort(key=lambda i: gt_blocks[i].order if gt_blocks[i].order is not None else 10**6)
        gt_text = " ".join(b.text for i in members if (b := gt_blocks[i]).text)
        cats = [gt_blocks[i].category for i in members]
        # 按预测块去重（同一个块可能同时是组内多个 GT 块的候选，重复拼接会把它的文本算多次）
        pred_texts: dict[int, tuple[int, str]] = {}
        for i in members:
            for p in per_gt_cands[i]:
                if p.text:
                    pred_texts[id(p)] = (p.seq, p.text)
        if cats[0] in CAPTION_KIND and pred_texts:
            # caption/footnote 取面积最小的候选：它们的候选锚在父块（表/图）bbox 上，面积不具
            # 分辨率；若把多个候选文本拼起来，无关字段会把相似度压低（实测面积比在好/坏配对间
            # 完全重叠，做尺寸过滤只会误杀，见 2026-09-12 实测）。
            smallest = min((p for i in members for p in per_gt_cands[i] if p.text), key=lambda p: _area(p.bbox))
            pred_text = smallest.text
        else:
            pred_text = " ".join(text for _, text in sorted(pred_texts.values()))
        if not gt_text and not pred_text:
            continue
        out.append(
            {
                "category": max(set(cats), key=cats.count),
                "categories": cats,
                "gt_text": gt_text,
                "pred_text": pred_text,
                "matched": any(per_gt_cands[i] for i in members),
                "gt_order": gt_blocks[members[0]].order,
            }
        )
    return out
