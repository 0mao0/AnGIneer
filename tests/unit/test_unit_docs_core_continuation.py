"""单测：MinerU 跨页段落空续页块的合并兜底。"""
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "services" / "docs-core" / "src"))

from docs_core.step04_structure.solo_engine import _merge_mineru_continuation_rows


def make_row(uid, page, seq, text, x0=0.1, y0=0.8, x1=0.9, y1=0.9, btype="paragraph"):
    return {
        "id": seq,
        "block_uid": uid,
        "block_type": btype,
        "page_idx": page,
        "block_seq": seq,
        "plain_text": text,
        "page_width": 1000.0,
        "page_height": 733.0,
        "bbox_abs_x1": x0 * 1000,
        "bbox_abs_y1": y0 * 733,
        "bbox_abs_x2": x1 * 1000,
        "bbox_abs_y2": y1 * 733,
    }


def middle_with_last_text(page_idx, last_text):
    return {
        "pdf_info": [
            {
                "page_idx": page_idx,
                "page_size": [1000, 733],
                "preproc_blocks": [
                    {
                        "type": "text",
                        "bbox": [0, 0, 100, 100],
                        "lines": [{"spans": [{"content": last_text}]}],
                    }
                ],
            }
        ]
    }


class EmptyContinuationMergeTest(unittest.TestCase):
    def test_merges_cut_paragraph_with_top_empty_block(self):
        rows = [
            make_row("p0:1", 0, 1, "4.1.12 高强度螺栓连接副应符合……《钢结构用高强度大六"),
            make_row("p1:1", 1, 2, "", y0=0.10, y1=0.18, x0=0.119, x1=0.926),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "《钢结构用高强度大六"))
        self.assertEqual(merged, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(rows[0]["page_bboxes"]), 2)
        self.assertEqual([p["page_idx"] for p in rows[0]["page_bboxes"]], [0, 1])
        self.assertEqual(rows[0]["merged_from"], ["p1:1"])

    def test_skips_when_page_bottom_text_has_terminal_punct(self):
        rows = [
            make_row("p0:1", 0, 1, "4.1.11 锚筋或锚板的材料……Q 235 钢。"),
            make_row("p1:1", 1, 2, "", y0=0.10, y1=0.18, x0=0.119, x1=0.926),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "Q 235 钢。"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_without_middle_evidence(self):
        rows = [
            make_row("p0:1", 0, 1, "某段落内容……未完成"),
            make_row("p1:1", 1, 2, "", y0=0.10, y1=0.18, x0=0.119, x1=0.926),
        ]
        merged = _merge_mineru_continuation_rows(rows, {})
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_non_paragraph_empty_block(self):
        rows = [
            make_row("p0:1", 0, 1, "某段落内容……未完成"),
            make_row("p1:1", 1, 2, "", y0=0.10, y1=0.18, x0=0.119, x1=0.926, btype="table"),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "某段落内容……未完成"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_when_target_has_text(self):
        rows = [
            make_row("p0:1", 0, 1, "某段落内容……未完成"),
            make_row("p1:1", 1, 2, "4.1.13 轨道、固定支座……", y0=0.10, y1=0.18),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "某段落内容……未完成"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_merges_short_title_fragment(self):
        rows = [
            make_row("p0:1", 0, 1, "(3)船闸总体设计、水工建筑物设计和输水系统设计的有关资"),
            make_row("p1:1", 1, 2, "料；", y0=0.10, y1=0.125, x0=0.125, x1=0.175, btype="title"),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "……设计的有关资"))
        self.assertEqual(merged, 1)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["plain_text"], "(3)船闸总体设计、水工建筑物设计和输水系统设计的有关资料；")
        self.assertEqual(len(rows[0]["page_bboxes"]), 2)
        self.assertEqual(rows[0]["merged_from"], ["p1:1"])

    def test_skips_numbered_heading_fragment(self):
        rows = [
            make_row("p0:1", 0, 1, "……未完成的段落"),
            make_row("p1:1", 1, 2, "4 材料和容许应力", y0=0.10, y1=0.14, btype="title"),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "……未完成的段落"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_fragment_without_punctuation_end(self):
        rows = [
            make_row("p0:1", 0, 1, "……未完成的段落"),
            make_row("p1:1", 1, 2, "结语", y0=0.10, y1=0.14, btype="title"),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "……未完成的段落"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_fragment_when_source_ends_with_punct(self):
        rows = [
            make_row("p0:1", 0, 1, "……完整的段落。"),
            make_row("p1:1", 1, 2, "料；", y0=0.10, y1=0.125, x0=0.125, x1=0.175, btype="title"),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "……完整的段落。"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)

    def test_skips_long_fragment(self):
        rows = [
            make_row("p0:1", 0, 1, "……未完成的段落"),
            make_row("p1:1", 1, 2, "角头螺栓、大六角螺母、垫圈技术条件》；", y0=0.10, y1=0.14),
        ]
        merged = _merge_mineru_continuation_rows(rows, middle_with_last_text(0, "……未完成的段落"))
        self.assertEqual(merged, 0)
        self.assertEqual(len(rows), 2)


if __name__ == "__main__":
    unittest.main()
