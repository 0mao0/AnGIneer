# -*- coding: utf-8 -*-
"""OmniDocBench predict 产物必须剥掉 content.md 首行 build_id 注释。

背景（2026-09-12 实踩）：评测器按文本块匹配算 Edit_dist，而 predict 下载的 content.md
首行是 step04 戳入的 `<!-- build_id: <hex> -->`。该行若留在预测里，会与首个文本块
合并成一条预测（`build_idXXX三角形上` vs GT `三角形上`），单页 text 指标从 0.06 抬到 0.83。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../scripts")))

import run_omnidocbench_eval as odb


class StripBuildIdHeaderTests(unittest.TestCase):
    def test_strips_build_id_first_line(self):
        md = "<!-- build_id: b77f20cf5817 -->\n三角形（上）\n\n正文\n"
        self.assertEqual(odb._strip_build_id_header(md), "三角形（上）\n\n正文\n")

    def test_strips_with_leading_blank_and_no_trailing_newline(self):
        md = "<!-- build_id: ffec001f92e6 -->\n任务驱动一：阅读例1"
        self.assertEqual(odb._strip_build_id_header(md), "任务驱动一：阅读例1")

    def test_keeps_markdown_without_header(self):
        md = "# 标题\n\n正文\n"
        self.assertEqual(odb._strip_build_id_header(md), md)

    def test_does_not_strip_build_id_outside_first_line(self):
        md = "正文首行\n<!-- build_id: b77f20cf5817 -->\n"
        self.assertEqual(odb._strip_build_id_header(md), md)

    def test_does_not_strip_other_comments(self):
        md = "<!-- 解析备注 -->\n正文\n"
        self.assertEqual(odb._strip_build_id_header(md), md)

    def test_handles_empty_and_blank(self):
        self.assertEqual(odb._strip_build_id_header(""), "")
        self.assertEqual(odb._strip_build_id_header("\n\n"), "\n\n")


if __name__ == "__main__":
    unittest.main()
