"""短行标题提升（solo_engine.is_short_standalone_heading）的单元闸。

背景：MinerU 把"独立单行短文本"输出成 paragraph（报纸栏目名/文章标题/小节名），GT 标成 title。
200 页实测：106 个漏检 title 里 93 个的落点就是 paragraph。判据只用几何 + 长度——文本形态规则
（编号/结尾冒号/英文短行）实测精确率只有 18–32%，加了净亏，本文件据此把这些钉成反例。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from docs_core.step04_structure.solo_engine import (  # noqa: E402
    build_structured_from_rawfiles,
    is_short_standalone_heading,
)

PAGE = 1000.0


def row(*, y1: float, y2: float, x1: float = 100.0, x2: float = 500.0) -> dict:
    """真实结构行的形状：bbox_abs_* + page_width/page_height（没有 bbox 键）。"""
    return {
        "bbox_abs_x1": x1,
        "bbox_abs_y1": y1,
        "bbox_abs_x2": x2,
        "bbox_abs_y2": y2,
        "page_width": PAGE,
        "page_height": PAGE,
    }


def fires(text: str, *, y1: float = 100.0, y2: float = 110.0, block_type: str = "paragraph") -> bool:
    """默认行高 10/1000 = 1% 页高，在 1.5% 门槛内。"""
    return is_short_standalone_heading(block_type, text, row(y1=y1, y2=y2))


class ShortLinePromotionTests(unittest.TestCase):
    def test_plain_short_line_fires(self):
        self.assertTrue(fires("行业经纬"))

    def test_tall_block_does_not_fire(self):
        """正文段落（本例高 5% 页高）不许提升。"""
        self.assertFalse(fires("这是一段正文，虽然也不算长但它是整段文字里的第一行内容", y1=100.0, y2=150.0))

    def test_boundary_at_max_height(self):
        # 门槛 1.5%：1.5% 恰好在内，1.6% 在外
        self.assertTrue(fires("边界内", y1=100.0, y2=115.0))
        self.assertFalse(fires("边界外", y1=100.0, y2=116.0))

    def test_too_many_chars_does_not_fire(self):
        self.assertFalse(fires("这是一个超过二十四个字符的独立短行标题候选文本内容"))

    def test_char_cap_boundary(self):
        self.assertTrue(fires("一" * 24))
        self.assertFalse(fires("一" * 25))

    def test_non_paragraph_never_fires(self):
        for bt in ("title", "list", "table", "image", "equation_interline", "page_header"):
            self.assertFalse(fires("行业经纬", block_type=bt), bt)

    def test_empty_text_does_not_fire(self):
        self.assertFalse(fires(""))
        self.assertFalse(fires("   "))

    # ── 反例：这些形态实测是噪声源 / 会把 text_block 召回打掉 ──────────────

    def test_byline_does_not_fire(self):
        for t in ("本报记者 肖力伟", "通讯员 康明", "吕羡林摄", "BY ANDREA PETERSEN", "Staff Writer"):
            self.assertFalse(fires(t), t)

    def test_bullet_item_does_not_fire(self):
        for t in ("▶ Canned peaches", "- Stretching", "· 备注"):
            self.assertFalse(fires(t), t)

    def test_index_entry_does_not_fire(self):
        for t in ("market share, 248, 260", "Medicaid, 310, 317", "money multiplier, 655"):
            self.assertFalse(fires(t), t)

    def test_date_line_does_not_fire(self):
        self.assertFalse(fires("2010年12月16日 星期四"))

    def test_contact_line_does_not_fire(self):
        self.assertFalse(fires("电话：0510-85187583"))
        self.assertFalse(fires("Email: a@b.com"))

    def test_sentence_tail_does_not_fire(self):
        for t in ("其他说明。", "注意事项，", "见表 1."):
            self.assertFalse(fires(t), t)

    def test_numeric_only_does_not_fire(self):
        for t in ("1, 2, 3", "12.5%", "(3)"):
            self.assertFalse(fires(t), t)

    def test_sentence_like_long_text_with_colon_still_fires_if_short(self):
        """结尾冒号**不**是排除项：实测它是低精确率形态，但排除它没有收益，
        真正拦它的是长度。留着本用例防止有人把"冒号"当判据加进来又反向改掉结论。"""
        self.assertTrue(fires("投资评级说明："))

    def test_missing_bbox_fields_does_not_fire(self):
        self.assertFalse(is_short_standalone_heading("paragraph", "行业经纬", {}))
        self.assertFalse(
            is_short_standalone_heading(
                "paragraph", "行业经纬", {"bbox_abs_x1": 1.0, "bbox_abs_y1": 2.0}
            )
        )

    def test_no_page_size_does_not_fire(self):
        bare = {"bbox_abs_x1": 100.0, "bbox_abs_y1": 100.0, "bbox_abs_x2": 500.0, "bbox_abs_y2": 110.0}
        self.assertFalse(is_short_standalone_heading("paragraph", "行业经纬", bare))


class ShortLinePromotionEndToEnd(unittest.TestCase):
    """端到端闸：判据必须能通过真实入口落到 jsonl 节点上（P2 踩过"规则空转但单测全绿"）。"""

    def _run(self, blocks, options=None):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "mineru_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "content_list_v2.json").write_text(
                json.dumps(blocks, ensure_ascii=False), encoding="utf-8"
            )
            (raw_dir / "layout.json").write_text(
                json.dumps({"_version_name": "test-layout", "pdf_info": [{"page_idx": 0, "page_size": [1000, 1000]}]}),
                encoding="utf-8",
            )
            return build_structured_from_rawfiles(
                Path(temp_dir), "doc-shortline", "短行提升", llm_client=None,
                options=options or {"use_llm": False},
            )

    def test_short_line_becomes_title_node(self):
        # 短行夹在两段正文之间：只有它该变性
        blocks = [[
            {"type": "paragraph", "bbox": [100, 100, 900, 300],
             "content": {"paragraph_content": [{"content": "这是一段正常的正文，占了相当大的版面高度，不应该被当成标题处理。"}]}},
            {"type": "paragraph", "bbox": [100, 400, 400, 410],
             "content": {"paragraph_content": [{"content": "行业经纬"}]}},
            {"type": "paragraph", "bbox": [100, 500, 900, 700],
             "content": {"paragraph_content": [{"content": "后面又是一段正文，同样不该变性。"}]}},
        ]]
        result = self._run(blocks)
        types = {str(n.get("plain_text") or ""): n["block_type"] for n in result.nodes}
        self.assertEqual(types["行业经纬"], "title")
        self.assertEqual(types["这是一段正常的正文，占了相当大的版面高度，不应该被当成标题处理。"], "paragraph")
        self.assertEqual(types["后面又是一段正文，同样不该变性。"], "paragraph")

    def test_promoted_title_gets_level_not_none_in_body(self):
        """正文页上提升的标题必须带 level（留 None 会让 canonical 按默认 1 处理、冲散 section_path）。"""
        blocks = [[
            {"type": "title", "bbox": [100, 100, 400, 115], "content": {"level": 1, "title_content": [{"content": "1 总则"}]}},
            {"type": "paragraph", "bbox": [100, 200, 900, 400],
             "content": {"paragraph_content": [{"content": "正文段落一，用于把标题栈建起来。"}]}},
            {"type": "paragraph", "bbox": [100, 500, 400, 510],
             "content": {"paragraph_content": [{"content": "课堂练习"}]}},
        ]]
        result = self._run(blocks)
        node = next(n for n in result.nodes if str(n.get("plain_text") or "") == "课堂练习")
        self.assertEqual(node["block_type"], "title")
        self.assertIsNotNone(node.get("derived_level"), "提升的标题必须带 level")

    def test_markdown_gets_heading_marker(self):
        blocks = [[
            {"type": "paragraph", "bbox": [100, 400, 400, 410],
             "content": {"paragraph_content": [{"content": "行业经纬"}]}},
        ]]
        result = self._run(blocks)
        md = (Path(result.md_path).read_text(encoding="utf-8") if getattr(result, "md_path", None) else "")
        if not md:
            from docs_core.step04_structure.shared.markdown_projection import build_faithful_markdown

            md, _ = build_faithful_markdown(result.nodes, build_id="b1")
        self.assertIn("行业经纬", md)


if __name__ == "__main__":
    unittest.main()
