# -*- coding: utf-8 -*-
"""结构层评测（jsonl 口径）的核心函数单测。

重点锁三处实踩过的坑：
1. TEDS 必须包成完整 HTML 文档（裸 <table> 片段连自己比自己都是 0.0）；
2. 块粒度不对等时不能逐块硬比（GT 按行标公式数组、我们合成一块 → 逐块比会全近 0）；
3. 相似度分母取两侧较长者，不产出负值。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from evals_core.parse_eval.corpus import _as_document, _score_teds, _score_text
from evals_core.parse_eval.jsonl_eval import (
    GtBlock,
    PredBlock,
    _build_groups,
    covered_ratio,
    eval_page,
    iou,
    norm_latex,
    norm_text,
    poly_to_bbox,
)


class TextNormTests(unittest.TestCase):
    def test_strips_markdown_heading_markers_from_gt_title(self):
        # GT 的 title.text 自带 markdown 井号，我们的不含——不剥掉标题类目会整体算错
        self.assertEqual(norm_text("### 4.6 Exploration SDP"), "4.6 Exploration SDP")

    def test_collapses_whitespace_and_newlines(self):
        self.assertEqual(norm_text("a \n  b\tc"), "a b c")

    def test_handles_none(self):
        self.assertEqual(norm_text(None), "")


class LatexNormTests(unittest.TestCase):
    def test_ignores_serialization_style(self):
        # 实测的 GT/MinerU 风格差异：\text{x} vs \text {x}、{2DV} vs 2 D V、\_ vs _
        gt = r"\# \left( \text{Params}\right) = {2DV} + {4D}"
        ours = r"\# (\text {Params}) = 2 D V + 4 D"
        self.assertEqual(norm_latex(gt), norm_latex(ours))

    def test_strips_wrappers_and_environments(self):
        self.assertEqual(norm_latex(r"$$\frac{a}{b}$$"), norm_latex(r"\frac{a}{b}"))
        self.assertEqual(norm_latex(r"\begin{equation}x\end{equation}"), norm_latex("x"))


class GeometryTests(unittest.TestCase):
    def test_poly_to_bbox_takes_extremes(self):
        self.assertEqual(poly_to_bbox([10, 20, 110, 20, 110, 40, 10, 40]), (10, 20, 110, 40))

    def test_poly_to_bbox_rejects_short_input(self):
        self.assertIsNone(poly_to_bbox([1, 2]))
        self.assertIsNone(poly_to_bbox(None))

    def test_iou_and_covered_ratio(self):
        a = (0.0, 0.0, 1.0, 1.0)
        b = (0.0, 0.0, 0.5, 1.0)
        self.assertAlmostEqual(iou(a, b), 0.5)
        self.assertAlmostEqual(covered_ratio(b, a), 1.0)   # b 完全被 a 覆盖
        self.assertAlmostEqual(covered_ratio(a, b), 0.5)   # a 只有一半落在 b 里


class TedsWrappingTests(unittest.TestCase):
    FRAGMENT = "<table><tr><td>a</td><td>b</td></tr><tr><td>1</td><td>2</td></tr></table>"

    def test_bare_fragment_needs_document_wrapper(self):
        # 官方 TEDS 走 xpath('body/table')：不包裹时自己比自己也是 0.0（实踩）
        self.assertEqual(_as_document(self.FRAGMENT), f"<html><body>{self.FRAGMENT}</body></html>")

    def test_self_comparison_is_one_after_wrapping(self):
        self.assertAlmostEqual(_score_teds(self.FRAGMENT, self.FRAGMENT), 1.0)

    def test_identical_table_scores_one(self):
        self.assertAlmostEqual(_score_teds(self.FRAGMENT, self.FRAGMENT), 1.0)

    def test_empty_prediction_scores_zero(self):
        self.assertEqual(_score_teds("", self.FRAGMENT), 0.0)

    def test_missing_gt_is_not_scored(self):
        self.assertIsNone(_score_teds(self.FRAGMENT, ""))


class ScoreTextTests(unittest.TestCase):
    def test_denominator_uses_longer_side_to_avoid_negative(self):
        # 我们的块常比 GT 长（多行公式合成一块）；除以 GT 长度会算出负值
        score = _score_text("x" * 40, "x" * 10)
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_identical_text_is_one(self):
        self.assertAlmostEqual(_score_text("abc", "abc"), 1.0)

    def test_empty_prediction_is_zero(self):
        self.assertEqual(_score_text("", "abc"), 0.0)

    def test_no_gt_text_is_unscored(self):
        self.assertIsNone(_score_text("abc", ""))


def _gt(category, bbox, order=0, text="", html=""):
    return GtBlock(category=category, bbox=bbox, order=order, text=text, html=html, is_table=category == "table")


def _pred(block_type, bbox, seq, text="", html="", **kw):
    return PredBlock(block_type=block_type, bbox=bbox, seq=seq, text=text, html=html, **kw)


class GroupingTests(unittest.TestCase):
    def test_gt_text_lines_covered_by_one_block_are_grouped(self):
        """GT 把一段文字切成 3 块，我们合成 1 块 → 应归为一组、文本拼接后比一次。"""
        gt_blocks = [
            _gt("text_block", (0.1, 0.10, 0.8, 0.14), order=1, text="a"),
            _gt("text_block", (0.1, 0.14, 0.8, 0.18), order=2, text="b"),
            _gt("text_block", (0.1, 0.18, 0.8, 0.22), order=3, text="c"),
        ]
        preds = [_pred("paragraph", (0.1, 0.10, 0.8, 0.22), 1, text="abc")]
        result = eval_page(gt_blocks, preds)
        self.assertEqual(len(result["groups"]), 1)
        group = result["groups"][0]
        self.assertEqual(group["gt_text"], "a b c")
        self.assertEqual(group["pred_text"], "abc")
        self.assertTrue(group["matched"])

    def test_equations_are_not_grouped_across_gt_blocks(self):
        """公式**不**跨 GT 块分组：公式按条比。

        分组会把多行公式拼成一个字符串，与逐条比较给出完全不同的数字——实测同一批 187 条配对
        逐条比两边都是 0.68，分组聚合后变成 MinerU 0.87 / 我们 0.50 的假差异（2026-09-13 实踩）。
        """
        gt_blocks = [
            _gt("equation_isolated", (0.1, 0.10, 0.8, 0.14), order=1, text="x"),
            _gt("equation_isolated", (0.1, 0.14, 0.8, 0.18), order=2, text="y"),
        ]
        preds = [_pred("equation_interline", (0.1, 0.10, 0.8, 0.18), 1, text="xy", math="xy")]
        result = eval_page(gt_blocks, preds)
        self.assertEqual(len(result["groups"]), 2, "每个 GT 公式应各自成组")
        self.assertEqual([g["gt_text"] for g in result["groups"]], ["x", "y"])

    def test_single_gt_block_with_smaller_predictions_groups_too(self):
        """反向：GT 一个大块被我们切成 2 段 → 也归一组，文本按 seq 拼接。"""
        gt_blocks = [_gt("text_block", (0.1, 0.10, 0.9, 0.30), order=1, text="hello world")]
        preds = [
            _pred("paragraph", (0.1, 0.10, 0.9, 0.19), 2, text="hello"),
            _pred("paragraph", (0.1, 0.19, 0.9, 0.30), 1, text="world"),
        ]
        result = eval_page(gt_blocks, preds)
        self.assertEqual(len(result["groups"]), 1)
        self.assertEqual(result["groups"][0]["pred_text"], "world hello")   # 按 seq 排序
