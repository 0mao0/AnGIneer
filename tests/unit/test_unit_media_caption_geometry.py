"""图表题注的几何兜底（2026-09-17 P2）。

题注原本只能靠文本匹配挂指针（needles 来自 MinerU 的 caption 字段），MinerU 不给该字段时
直接 `return {}`——实测 200 页里 caption 类的召回只有一半上下。题注在版面上就是紧贴图/表
的那块文字，位置本身够判别。

**夹具必须用真实行形状**（bbox_abs_x1..y2 + page_width/page_height）。首版夹具自造了
`row["bbox"]`，而结构行里没有这个键 → 兜底全程空转、200 页 A/B 精确 Δ0；单元测试却是绿的。
末尾的 TestGeometryActuallyFiresEndToEnd 就是为这类"字段名漂移"补的闸。
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
for rel in ("services/docs-core/src",):
    p = os.path.join(ROOT, rel)
    if p not in sys.path:
        sys.path.insert(0, p)

from docs_core.step04_structure.solo_engine import (  # noqa: E402
    build_structured_from_rawfiles,
    collect_media_related_block_refs,
    geometric_caption_uid,
    media_row_bbox_norm,
)

PAGE_W = PAGE_H = 1000.0


def node(uid, block_type, bbox_norm, text="", page=0, **extra):
    """按结构行的真实形状造行：归一 bbox → 页面绝对坐标。"""
    x0, y0, x1, y1 = bbox_norm
    row = {
        "block_uid": uid,
        "block_type": block_type,
        "plain_text": text,
        "page_idx": page,
        "content_json": {},
        "page_width": PAGE_W,
        "page_height": PAGE_H,
        "bbox_abs_x1": x0 * PAGE_W,
        "bbox_abs_y1": y0 * PAGE_H,
        "bbox_abs_x2": x1 * PAGE_W,
        "bbox_abs_y2": y1 * PAGE_H,
    }
    row.update(extra)
    return row


IMAGE = node("img1", "image", [0.2, 0.30, 0.6, 0.50])
TABLE = node("tab1", "table", [0.2, 0.50, 0.6, 0.70])
BELOW = node("p_below", "paragraph", [0.2, 0.51, 0.6, 0.55], "图 1 试点区域平面布置")
ABOVE = node("p_above", "paragraph", [0.2, 0.25, 0.6, 0.29], "上一段正文")


class BboxNormTests(unittest.TestCase):
    def test_normalizes_by_page_size(self):
        self.assertEqual(media_row_bbox_norm(node("x", "image", [0.1, 0.2, 0.3, 0.4])),
                         (0.1, 0.2, 0.3, 0.4))

    def test_1000_scale_page(self):
        """页尺寸远小于坐标 → 按 1000 尺度归一（与 nx/ny 同口径）。"""
        row = {"bbox_abs_x1": 100, "bbox_abs_y1": 200, "bbox_abs_x2": 500, "bbox_abs_y2": 600,
               "page_width": 200, "page_height": 260}
        self.assertEqual(media_row_bbox_norm(row), (0.1, 0.2, 0.5, 0.6))

    def test_missing_abs_fields_returns_none(self):
        """结构行没有 `bbox` 键——回归闸：几何口径若改回读它是拿不到东西的。"""
        self.assertIsNone(media_row_bbox_norm({"block_uid": "a", "page_idx": 0}))


class GeometricCaptionTests(unittest.TestCase):
    def test_image_prefers_below(self):
        rows = [IMAGE, ABOVE, BELOW]
        self.assertEqual(geometric_caption_uid(IMAGE, rows, "image"), "p_below")

    def test_table_prefers_above(self):
        tcap = node("p_tcap", "paragraph", [0.2, 0.45, 0.6, 0.49], "表 3 材料用量表")
        tnote = node("p_tnote", "paragraph", [0.2, 0.71, 0.6, 0.75], "注：数据来源见附录")
        self.assertEqual(geometric_caption_uid(TABLE, [TABLE, tcap, tnote], "table"), "p_tcap")

    def test_falls_back_to_other_side_when_preferred_side_empty(self):
        """表题上方没有时可用下方（部分版式表注在下一行）。"""
        tnote = node("p_below_tab", "paragraph", [0.2, 0.71, 0.6, 0.74], "表 4 明细")
        self.assertEqual(geometric_caption_uid(TABLE, [TABLE, tnote], "table"), "p_below_tab")

    def test_too_far_is_not_attached(self):
        far = node("p_far", "paragraph", [0.2, 0.66, 0.6, 0.70], "隔了很远的一段正文")
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, far], "image"), "")

    def test_other_column_is_not_attached(self):
        other = node("p_other", "paragraph", [0.80, 0.51, 0.95, 0.55], "右栏文字")
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, other], "image"), "")

    def test_heading_candidate_is_skipped(self):
        head = node("t1", "paragraph", [0.2, 0.51, 0.6, 0.55], "4.2 施工组织设计")
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, head], "image"), "")

    def test_nearest_wins(self):
        near = node("p_near", "paragraph", [0.2, 0.505, 0.6, 0.53], "图 1 最近的题注")
        far = node("p_far2", "paragraph", [0.2, 0.54, 0.6, 0.57], "再下面一段")
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, far, near], "image"), "p_near")

    def test_missing_or_bad_bbox_returns_empty(self):
        no_bbox = {"block_uid": "img2", "block_type": "image", "plain_text": "", "page_idx": 0}
        self.assertEqual(geometric_caption_uid(no_bbox, [BELOW], "image"), "")
        bad = node("img3", "image", [0.2, 0.3, 0.6, 0.5])
        bad["bbox_abs_x2"] = None
        self.assertEqual(geometric_caption_uid(bad, [BELOW], "image"), "")

    def test_other_page_is_not_attached(self):
        other_page = node("p_p2", "paragraph", [0.2, 0.51, 0.6, 0.55], "下一页的文字", page=1)
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, other_page], "image"), "")

    def test_tall_candidate_is_not_a_caption(self):
        """正文段落比题注高得多（GT caption 高度 p90=5.5% 页高）——报版"图在上正文在下"靠这条挡住。"""
        body = node("p_body", "paragraph", [0.2, 0.51, 0.6, 0.62], "这是一整段正文，占了页面 11% 的高度")
        self.assertEqual(geometric_caption_uid(IMAGE, [IMAGE, body], "image"), "")

    def test_char_cap_knob_is_off_by_default(self):
        """长度门槛默认关（开与否只减量不提纯，取舍表见 docs/parse-struct-eval.md）。"""
        import docs_core.step04_structure.solo_engine as se
        self.assertEqual(se._MEDIA_CAPTION_MAX_CHARS, 0)


class RefCollectionIntegrationTests(unittest.TestCase):
    def test_geometry_used_only_when_no_caption_text(self):
        """有 caption 文本时走文本匹配（不抢几何块）；没文本时才几何兜底。"""
        with_text = dict(IMAGE, content_json={"image_caption": [{"type": "text", "content": "系统架构图"}]})
        refs = collect_media_related_block_refs(with_text, [with_text, BELOW])
        self.assertEqual(refs, {})                       # 文本对不上就不挂（沿用原行为）

        refs_geo = collect_media_related_block_refs(IMAGE, [IMAGE, BELOW])
        self.assertEqual(refs_geo.get("caption_block_uids"), ["p_below"])

    def test_no_candidate_returns_empty(self):
        self.assertEqual(collect_media_related_block_refs(IMAGE, [IMAGE]), {})


class TestMarkdownUnaffectedByCaptionPointers(unittest.TestCase):
    """A① 读 markdown 投影，而投影只读 plain_text / caption 字段——指针变化不得改变 markdown 字节。

    这是"P2 不影响 A①"的代码级依据（docs/parse-struct-eval.md 题注指针节的声明）。
    """

    def _md(self, extra):
        from docs_core.step04_structure.shared.markdown_projection import build_faithful_markdown
        table = {
            "block_uid": "t1", "block_type": "table", "page_idx": 0, "block_seq": 1,
            "plain_text": "", "table_html": "<table><tr><td>A</td></tr></table>",
        }
        table.update(extra)
        rows = [table, {
            "block_uid": "p1", "block_type": "paragraph", "page_idx": 0, "block_seq": 2,
            "plain_text": "正文一段",
        }]
        text, _ = build_faithful_markdown(rows, build_id="b1", include_furniture=False, html_tables=True)
        return text

    def test_same_markdown_with_and_without_pointer(self):
        self.assertEqual(self._md({}), self._md({"caption_block_uids": ["p1"], "caption": None}))

    def test_caption_field_still_renders(self):
        self.assertIn("表 1 题注", self._md({"caption": "表 1 题注"}))


class TestGeometryActuallyFiresEndToEnd(unittest.TestCase):
    """端到端闸：几何兜底必须能在真实解析入口上产出 caption_block_uids。

    这里刻意不 stub——走 build_structured_from_rawfiles 读 mineru_raw，覆盖
    "行字段名 / 归一化口径" 这一层。若兜底又变成空转，本用例会红。
    """

    def _run(self, blocks):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_dir = Path(temp_dir) / "mineru_raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            (raw_dir / "content_list_v2.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
            (raw_dir / "layout.json").write_text(json.dumps({
                "_version_name": "test-layout",
                "pdf_info": [{"page_idx": 0, "page_size": [1000, 1000]}],
            }), encoding="utf-8")
            return build_structured_from_rawfiles(
                Path(temp_dir), "doc-geo", "几何兜底", llm_client=None, options={"use_llm": False}
            )

    def test_table_without_caption_text_gets_geometric_caption(self):
        # 表在上、题注文字在下：content_list 不给 table_caption → 只能靠几何兜底
        blocks = [[
            {"type": "table", "bbox": [200, 300, 800, 550],
             "content": {"html": "<table><tr><td>A</td></tr></table>"}},
            {"type": "paragraph", "bbox": [200, 560, 800, 600],
             "content": {"paragraph_content": [{"content": "表 7 几何兜底验证"}]}},
        ]]
        result = self._run(blocks)
        table = next(n for n in result.nodes if n["block_type"] == "table")
        caption = next(n for n in result.nodes if "几何兜底验证" in str(n.get("plain_text") or ""))
        self.assertEqual(table.get("caption_block_uids"), [caption["block_uid"]])
        self.assertIn(caption["block_uid"], [u for u in table["caption_block_uids"]])

    def test_body_text_far_below_is_not_attached(self):
        """正文离得远（>4.5% 页高）不许被挂成题注——这是 P2 最大的翻车面。"""
        blocks = [[
            {"type": "table", "bbox": [200, 300, 800, 550],
             "content": {"html": "<table><tr><td>A</td></tr></table>"}},
            {"type": "paragraph", "bbox": [200, 620, 800, 700],
             "content": {"paragraph_content": [{"content": "这是正文，不是题注"}]}},
        ]]
        result = self._run(blocks)
        table = next(n for n in result.nodes if n["block_type"] == "table")
        self.assertFalse(table.get("caption_block_uids"))


if __name__ == "__main__":
    unittest.main()
