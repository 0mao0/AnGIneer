"""MinerU 分块产物合并：dict 型 middle.json（hybrid 后端）必须与 list 型一样参与合并。"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from docs_core.step03_mineru_parse.mineru_parser import MinerUParser  # noqa: E402


def _write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _chunk_middle(page_count: int, start_idx: int = 0) -> dict:
    return {
        "pdf_info": [
            {
                "page_idx": start_idx + i,
                "page_size": [595, 841],
                "preproc_blocks": [],
                "para_blocks": [],
            }
            for i in range(page_count)
        ],
        "_backend": "hybrid",
        "_version_name": "3.4.4",
    }


class MineruChunkMergeTests(unittest.TestCase):
    def test_dict_middle_json_merged_with_page_offset(self):
        parser = MinerUParser()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            _write(out / "middle.json", _chunk_middle(2))
            _write(out / "middle_chunk2.json", _chunk_middle(1))

            parser._merge_single_chunk_json(
                chunk_dir=out,
                output_dir=out,
                chunk_idx=1,
                page_offset=2,
                _json=json,
            )

            merged = json.loads((out / "middle.json").read_text(encoding="utf-8"))
            self.assertEqual([p["page_idx"] for p in merged["pdf_info"]], [0, 1, 2])
            self.assertEqual(merged["_backend"], "hybrid")
            self.assertEqual(merged["_version_name"], "3.4.4")
            self.assertEqual(merged["pdf_info"][2]["page_size"], [595, 841])

    def test_chunk_merge_keeps_full_middle_json_for_hybrid_dict(self):
        parser = MinerUParser()
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            chunk_dirs = [Path(tmp) / f"chunk{i}" for i in range(3)]
            chunk_sizes = [2, 2, 1]
            for chunk_dir, size in zip(chunk_dirs, chunk_sizes):
                _write(
                    chunk_dir / "content_list_v2.json",
                    [[{"type": "paragraph", "content": {"paragraph_content": []}}] for _ in range(size)],
                )
                _write(chunk_dir / "middle.json", _chunk_middle(size))

            for idx, chunk_dir in enumerate(chunk_dirs):
                parser._merge_dir_contents(chunk_dir, out, chunk_idx=idx)
            parser._merge_chunk_json_artifacts(out, [str(d) for d in chunk_dirs])

            cl = json.loads((out / "content_list_v2.json").read_text(encoding="utf-8"))
            middle = json.loads((out / "middle.json").read_text(encoding="utf-8"))
            self.assertEqual(len(cl), 5)
            self.assertEqual([p["page_idx"] for p in middle["pdf_info"]], [0, 1, 2, 3, 4])
            self.assertFalse((out / "middle_chunk2.json").exists())
            self.assertFalse((out / "middle_chunk3.json").exists())
