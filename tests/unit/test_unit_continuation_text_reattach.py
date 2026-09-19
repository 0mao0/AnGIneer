"""续接文本重归属（_reattach_merged_continuation_text）的单元闸。

背景（2026-09-19，200 页实测）：MinerU 段落装配会把续接段落并入前一块的文本，却在
content_list_v2 里留下 bbox 正确、content 为空的 paragraph。实测 121 例里 105 例的
承载块是同页紧邻的前一个 paragraph、被并文本是它的结尾后缀。不处理会导致该块文本与其
bbox 不一致（检索引用高亮落错区域），且空块与 GT 对齐时文本相似度恒为 0。
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "services" / "docs-core" / "src"))

from docs_core.step04_structure import solo_engine  # noqa: E402
from docs_core.step04_structure.solo_engine import (  # noqa: E402
    _reattach_merged_continuation_text,
    _suffix_cut_index,
    build_structured_from_rawfiles,
)


def row(*, text: str, y1: float, y2: float, block_type: str = "paragraph", page: int = 0,
        x1: float = 100.0, x2: float = 900.0) -> dict:
    """真实结构行形状：bbox_abs_*（0–1000）+ page_width/page_height。"""
    return {
        "block_type": block_type,
        "page_idx": page,
        "plain_text": text,
        "bbox_abs_x1": x1, "bbox_abs_y1": y1, "bbox_abs_x2": x2, "bbox_abs_y2": y2,
        "page_width": 1000.0, "page_height": 1000.0,
    }


def middle(*, page: int = 0, blocks: list[tuple[list[float], str]]) -> dict:
    return {
        "pdf_info": [{
            "page_idx": page,
            "page_size": [1000, 1000],
            "preproc_blocks": [
                {"type": "text", "bbox": list(bbox),
                 "lines": [{"spans": [{"type": "text", "content": text}]}]}
                for bbox, text in blocks
            ],
        }]
    }


class SuffixCutIndexTests(unittest.TestCase):
    def test_plain_suffix(self):
        self.assertEqual(_suffix_cut_index("前文续接段", "续接段"), 2)

    def test_whitespace_insensitive(self):
        self.assertEqual(_suffix_cut_index("前文 续接段", "续接段"), 3)

    def test_not_a_suffix_returns_none(self):
        self.assertIsNone(_suffix_cut_index("前文续接段", "前文"))

    def test_empty_suffix_returns_none(self):
        self.assertIsNone(_suffix_cut_index("abc", ""))
        self.assertIsNone(_suffix_cut_index("", "abc"))

    def test_whole_string(self):
        self.assertEqual(_suffix_cut_index("续接段", "续接段"), 0)


class ReattachTests(unittest.TestCase):
    TAIL = "续接段落的正文内容足够长"

    PREFIX = "左栏正文开头的内容足够长。"

    def _rows(self, host_text: str, host_type: str = "paragraph", same_page: bool = True):
        return [
            row(text=host_text, y1=100.0, y2=300.0, block_type=host_type),
            row(text="", y1=320.0, y2=400.0, page=0 if same_page else 1),
        ]

    def _mid(self):
        # 空块 bbox 归一 (0.1,0.32,0.9,0.4) × page_size 1000 = 像素 bbox
        return middle(blocks=[([100.0, 320.0, 900.0, 400.0], self.TAIL)])

    def test_suffix_is_moved_and_host_trimmed(self):
        rows = self._rows(self.PREFIX + self.TAIL)
        n = _reattach_merged_continuation_text(rows, self._mid())
        self.assertEqual(n, 1)
        self.assertEqual(rows[1]["plain_text"], self.TAIL)
        self.assertEqual(rows[0]["plain_text"], self.PREFIX)

    def test_text_not_at_tail_is_left_alone(self):
        rows = self._rows(self.TAIL + self.PREFIX)
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)
        self.assertEqual(rows[1]["plain_text"], "")
        self.assertEqual(rows[0]["plain_text"], self.TAIL + self.PREFIX)

    def test_missing_middle_payload_is_noop(self):
        rows = self._rows(self.PREFIX + self.TAIL)
        self.assertEqual(_reattach_merged_continuation_text(rows, None), 0)
        self.assertEqual(rows[1]["plain_text"], "")

    def test_no_host_before_block_is_noop(self):
        rows = self._rows("")
        rows[1]["plain_text"] = ""
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)

    def test_host_on_other_page_is_not_used(self):
        """跨页续接由 _merge_mineru_continuation_rows 负责，这里不许动。"""
        rows = self._rows("左栏正文。" + self.TAIL, same_page=False)
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)

    def test_host_must_be_paragraph(self):
        rows = self._rows("左栏正文。" + self.TAIL, host_type="title")
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)

    def test_host_would_be_gutted_so_skip(self):
        """承载块整段都是这段续文时不许动它——否则只是把一个空块换成另一个空块。"""
        rows = self._rows(self.TAIL)
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)
        self.assertEqual(rows[0]["plain_text"], self.TAIL)
        self.assertEqual(rows[1]["plain_text"], "")

    def test_too_short_remainder_is_skipped(self):
        """剩余不足 _REATTACH_MIN_REMAIN 时跳过（真实数据里剩余最小 8 字，未触发）。"""
        rows = self._rows("短。" + self.TAIL)
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)
        self.assertEqual(rows[0]["plain_text"], "短。" + self.TAIL)

    def test_too_short_continuation_is_skipped(self):
        short = "太短"
        rows = self._rows(self.PREFIX + short)
        mid = middle(blocks=[([100.0, 320.0, 900.0, 400.0], short)])
        self.assertEqual(_reattach_merged_continuation_text(rows, mid), 0)

    def test_non_paragraph_empty_block_is_not_touched(self):
        rows = self._rows(self.PREFIX + self.TAIL)
        rows[1]["block_type"] = "title"
        self.assertEqual(_reattach_merged_continuation_text(rows, self._mid()), 0)

    def test_empty_block_without_preproc_text_is_noop(self):
        rows = self._rows(self.PREFIX + self.TAIL)
        self.assertEqual(_reattach_merged_continuation_text(rows, middle(blocks=[])), 0)
        self.assertEqual(rows[1]["plain_text"], "")


class ReattachFiresEndToEnd(unittest.TestCase):
    """端到端闸：必须能在真实解析入口上把文本从承载块搬到空块。

    这里刻意不 stub——走 build_structured_from_rawfiles 读 mineru_raw，覆盖
    "middle.json 的坐标口径 / 行字段名" 这一层。若重归属又变成空转，本用例会红。
    """

    TAIL = "续接段落在另一块版面上的正文"

    def _run(self, blocks, mid):
        with tempfile.TemporaryDirectory() as temp_dir:
            raw = Path(temp_dir) / "mineru_raw"
            raw.mkdir(parents=True, exist_ok=True)
            (raw / "content_list_v2.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
            (raw / "layout.json").write_text(
                json.dumps({"_version_name": "t", "pdf_info": [{"page_idx": 0, "page_size": [1000, 1000]}]}),
                encoding="utf-8",
            )
            (raw / "middle.json").write_text(json.dumps(mid, ensure_ascii=False), encoding="utf-8")
            return build_structured_from_rawfiles(
                Path(temp_dir), "doc-reattach", "续接重归属", llm_client=None, options={"use_llm": False}
            )

    def test_text_moves_from_host_to_empty_block(self):
        blocks = [[
            {"type": "paragraph", "bbox": [100, 100, 900, 300],
             "content": {"paragraph_content": [{"content": "左栏正文开头的内容足够长。" + self.TAIL}]}},
            {"type": "paragraph", "bbox": [100, 320, 900, 400],
             "content": {"paragraph_content": []}},
        ]]
        mid = middle(blocks=[([100.0, 320.0, 900.0, 400.0], self.TAIL)])
        result = self._run(blocks, mid)
        texts = [str(n.get("plain_text") or "") for n in result.nodes if n.get("block_type") == "paragraph"]
        self.assertIn(self.TAIL, texts, "空块没有拿到被并走的文本")
        self.assertIn("左栏正文开头的内容足够长。", texts, "承载块尾部没有被摘掉")
        self.assertNotIn("左栏正文开头的内容足够长。" + self.TAIL, texts, "承载块仍带着别人的文本")
        self.assertEqual(result.stats.get("continuation_text_reattaches"), 1)

    def test_no_duplicate_text_in_document(self):
        """重归属的底线：同一段文本在文档里只许出现一次。"""
        blocks = [[
            {"type": "paragraph", "bbox": [100, 100, 900, 300],
             "content": {"paragraph_content": [{"content": "左栏正文开头的内容足够长。" + self.TAIL}]}},
            {"type": "paragraph", "bbox": [100, 320, 900, 400],
             "content": {"paragraph_content": []}},
        ]]
        mid = middle(blocks=[([100.0, 320.0, 900.0, 400.0], self.TAIL)])
        result = self._run(blocks, mid)
        joined = "".join(str(n.get("plain_text") or "") for n in result.nodes)
        self.assertEqual(joined.count(self.TAIL), 1, "文本被重复计入")


if __name__ == "__main__":
    unittest.main()
