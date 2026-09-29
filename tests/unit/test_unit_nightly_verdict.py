"""nightly 结论「评价」列文案：delta 是净差，净提升不等于零题转错。

2026-09-29 实踩：净 +1.83pp 的 run 里 50 题由对转错（matrix fp=50），卡片仍写「没有题目变差」
——该句只在配对零题转错时才成立，故改为报转错题数。
"""
import os
import sys
import unittest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
P = os.path.join(ROOT, "services", "evals-core", "src")
if P not in sys.path:
    sys.path.insert(0, P)

from evals_core.nightly import archive  # noqa: E402


class TestVerdict(unittest.TestCase):
    def test_net_gain_with_regressions_reports_count(self):
        # 09-29 那晚的真实形状：净 +1.83pp、50 题转错
        self.assertEqual(archive.verdict("green", 0.0183, 50), "提升 2pp，另有 50 题转错")

    def test_net_gain_without_regressions_keeps_old_wording(self):
        self.assertEqual(archive.verdict("green", 0.0183, 0), "提升 2pp，没有题目变差")

    def test_flat_with_regressions_reports_count(self):
        self.assertEqual(archive.verdict("green", 0.004, 7), "与基线持平，另有 7 题转错")

    def test_flat_without_regressions_keeps_old_wording(self):
        self.assertEqual(archive.verdict("green", 0.004, 0), "与基线持平，没有变差")

    def test_pp_rounding_boundary(self):
        # pp = round(delta*100)，Python 半偶舍入：0.5→0、1.5→2（不是「四舍五入」）
        self.assertEqual(archive.verdict("green", 0.005, 0), "与基线持平，没有变差")
        self.assertEqual(archive.verdict("green", 0.006, 0), "提升 1pp，没有题目变差")
        self.assertEqual(archive.verdict("green", 0.015, 0), "提升 2pp，没有题目变差")

    def test_drop_branch_unchanged(self):
        # 回落档不改：它从不说「没有变差」，只报方向
        self.assertEqual(archive.verdict("green", -0.02, 30), "回落 2pp，正常波动")

    def test_red_and_error_unchanged(self):
        self.assertEqual(archive.verdict("red", -0.03, 12), "回退 12 题，需排查")
        self.assertEqual(archive.verdict("red", -0.03, 0), "整体变差，需排查")
        self.assertEqual(archive.verdict("error", None, 0), "评测中断，未出结果")

    def test_no_baseline_unchanged(self):
        self.assertEqual(archive.verdict("green", None, 0), "无基线可比，未见变差")

    def test_within_twenty_chars(self):
        # 「评价」列宽有限（docstring 契约 ≤20 字），极端题数也不能撑爆
        for s in (archive.verdict("green", 0.0183, 50), archive.verdict("green", 0.0183, 0),
                  archive.verdict("green", 0.004, 7), archive.verdict("green", 0.004, 0),
                  archive.verdict("green", -0.02, 30), archive.verdict("green", 0.5, 120),
                  archive.verdict("red", -0.03, 12), archive.verdict("error", None, 0)):
            self.assertLessEqual(len(s), 20, s)


if __name__ == "__main__":
    unittest.main()
