# -*- coding: utf-8 -*-
"""extract_plain_text 的块类型覆盖测试。

背景（2026-09-12 结构层评测实测）：chart / page_footnote / page_aside_text / code / algorithm
五类块没有分支，落到末尾 `return ""`，导致 content_json 里的文本被整条吃掉——plain_text 为空，
`build_node_text` 取不到，canonical chunk 为空，FTS/向量索引里没有这段；markdown 投影同样只读
plain_text，也不含。后果是参考文献脚注、图表标题、代码正文不可检索、不可见。
"""
import os
import sys
import unittest

sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../services/docs-core/src"))
)

from docs_core.step04_structure.solo_engine import extract_plain_text


def spans(*texts):
    return [{"type": "text", "content": t} for t in texts]


class PreviouslyMissingTypesTests(unittest.TestCase):
    """这五类曾被漏掉——本组用例在缺分支时会失败。"""

    def test_chart_caption_and_footnote(self):
        content = {"chart_caption": spans("图1 架构"), "chart_footnote": spans("数据来源：内部")}
        self.assertEqual(extract_plain_text("chart", content), "图1 架构 数据来源：内部")

    def test_chart_without_caption_returns_empty(self):
        self.assertEqual(extract_plain_text("chart", {"image_source": "images/x.jpg"}), "")

    def test_page_footnote(self):
        content = {"page_footnote_content": spans("1 [法]布吕奈尔. 什么是比较文学[M].")}
        self.assertEqual(extract_plain_text("page_footnote", content), "1 [法]布吕奈尔. 什么是比较文学[M].")

    def test_page_aside_text(self):
        self.assertEqual(extract_plain_text("page_aside_text", {"page_aside_text_content": spans("Glossary")}), "Glossary")

    def test_code_caption_and_body(self):
        content = {"code_caption": spans("示例 1"), "code_content": spans("var a = 1;", "var b = 2;"), "code_language": "js"}
        self.assertEqual(extract_plain_text("code", content), "示例 1 var a = 1;var b = 2;")

    def test_algorithm_caption_and_body(self):
        content = {"algorithm_caption": [], "algorithm_content": spans("The transpose", " of a matrix")}
        self.assertEqual(extract_plain_text("algorithm", content), "The transpose of a matrix")

    def test_mixed_span_types_keep_order(self):
        content = {
            "algorithm_content": [
                {"type": "text", "content": "The transpose "},
                {"type": "equation_inline", "content": r"\mathbf{A}^{\mathsf{T}}"},
                {"type": "text", "content": " of a matrix"},
            ]
        }
        self.assertEqual(extract_plain_text("algorithm", content), r"The transpose \mathbf{A}^{\mathsf{T}} of a matrix")


class ExistingTypesRegressionTests(unittest.TestCase):
    """原有分支不得被本次改动影响。"""

    def test_image_caption_and_footnote(self):
        content = {"image_caption": spans("tell jokes"), "image_footnote": spans("来源：AP")}
        self.assertEqual(extract_plain_text("image", content), "tell jokes 来源：AP")

    def test_table_caption_and_footnote(self):
        content = {"table_caption": spans("表 15 估值表"), "table_footnote": spans("资料来源：iFind")}
        self.assertEqual(extract_plain_text("table", content), "表 15 估值表 资料来源：iFind")

    def test_paragraph_and_title(self):
        self.assertEqual(extract_plain_text("paragraph", {"paragraph_content": spans("正文")}), "正文")
        self.assertEqual(extract_plain_text("title", {"title_content": spans("4.6 小结")}), "4.6 小结")

    def test_list_items(self):
        content = {"list_items": [{"item_content": spans("第一项")}, {"item_content": spans("第二项")}]}
        self.assertEqual(extract_plain_text("list", content), "第一项 第二项")

    def test_equation_interline_uses_math_content(self):
        self.assertEqual(extract_plain_text("equation_interline", {"math_content": r" E = mc^2 "}), r"E = mc^2")


class EdgeCasesTests(unittest.TestCase):
    def test_unknown_type_returns_empty(self):
        self.assertEqual(extract_plain_text("no_such_type", {"x": spans("y")}), "")

    def test_empty_content_returns_empty(self):
        for block_type in ("chart", "page_footnote", "page_aside_text", "code", "algorithm"):
            self.assertEqual(extract_plain_text(block_type, {}), "")

    def test_missing_spans_key_returns_empty(self):
        self.assertEqual(extract_plain_text("page_footnote", {"other_key": spans("x")}), "")


if __name__ == "__main__":
    unittest.main()
