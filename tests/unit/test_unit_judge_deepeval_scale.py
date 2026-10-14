# -*- coding: utf-8 -*-
"""判分刻度假定单测（judge_deepeval 双刻度归一化 + rubric 刻度语言）。

2026-10-14 实踩：rubric 用 0–1 语言 → 判官照抄写 "score": 1（0–1 刻度满分）→ 归一化
对 ==1「不猜」保留 1 → DeepEval 按 0–10 除 10 成 0.1，两题满分被判挂（eval_1 q_020/q_022）。
修复 = rubric 刻度统一 0–10（满分写 10），1 回归「1/10」本义；(0,1) 小数档仍兜底 ×10。
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/evals-core/src")))

from evals_core.runner.judge_deepeval import (  # noqa: E402
    _GEVAL_CRITERIA,
    _GEVAL_STEPS,
    _normalize_judge_score_scale,
)


class JudgeScaleTests(unittest.TestCase):
    def test_rubric_speaks_0_to_10_scale(self):
        """判官是照抄 rubric 打分的：刻度语言必须是 0–10，且明示不要写 0–1 小数。"""
        self.assertIn("10=完整包含", _GEVAL_CRITERIA)
        self.assertIn("0–10", _GEVAL_CRITERIA)
        steps = "".join(_GEVAL_STEPS)
        self.assertIn("=10", steps)
        self.assertIn("10 或 9", steps)

    def test_decimal_0_1_scale_rescaled(self):
        text, raw, fixed = _normalize_judge_score_scale('{"score": 0.8, "reason": "x"}')
        self.assertTrue(fixed)
        self.assertAlmostEqual(raw, 0.8)
        self.assertEqual(json.loads(text)["score"], 8)

    def test_score_one_kept_as_1_of_10(self):
        """0–10 刻度下 1 就是「1 分」，原样保留（满分歧义已由 rubric 统一消除，不再猜）。"""
        text, raw, fixed = _normalize_judge_score_scale('{"score": 1, "reason": "x"}')
        self.assertFalse(fixed)
        self.assertEqual(raw, 1.0)
        self.assertEqual(json.loads(text)["score"], 1)

    def test_int_10_untouched(self):
        text, raw, fixed = _normalize_judge_score_scale('{"score": 10, "reason": "x"}')
        self.assertFalse(fixed)
        self.assertEqual(json.loads(text)["score"], 10)

    def test_unparsable_returns_raw(self):
        text, raw, fixed = _normalize_judge_score_scale("not json")
        self.assertFalse(fixed)
        self.assertIsNone(raw)
        self.assertEqual(text, "not json")


if __name__ == "__main__":
    unittest.main()
