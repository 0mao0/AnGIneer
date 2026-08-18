"""graph meta pages 兜底：middle.json 页数不完整时使用节点 page_width/height。"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../src")))

from docs_core.step04_structure.solo2json_pipeline import _build_graph_pages  # noqa: E402


def _write_middle(path: Path, pdf_info: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pdf_info": pdf_info}, ensure_ascii=False), encoding="utf-8")


def _nodes(count: int) -> list:
    return [{"page_idx": i, "page_width": 1000.0, "page_height": 1000.0} for i in range(count)]


def test_build_graph_pages_falls_back_when_middle_truncated(tmp_path):
    _write_middle(tmp_path / "middle.json", [
        {"page_idx": 0, "page_size": [595, 841]},
    ])
    with patch(
        "docs_core.step04_structure.solo2json_pipeline.paths.get_mineru_raw_dir",
        return_value=tmp_path,
    ):
        page_count, pages = _build_graph_pages("lib", "doc", _nodes(3))
    assert page_count == 3
    assert [p["pageIdx"] for p in pages] == [0, 1, 2]
    assert pages[0]["width"] == 1000.0


def test_build_graph_pages_prefers_complete_middle(tmp_path):
    _write_middle(tmp_path / "middle.json", [
        {"page_idx": 0, "page_size": [595, 841]},
        {"page_idx": 1, "page_size": [841, 595]},
        {"page_idx": 2, "page_size": [595, 841]},
    ])
    with patch(
        "docs_core.step04_structure.solo2json_pipeline.paths.get_mineru_raw_dir",
        return_value=tmp_path,
    ):
        page_count, pages = _build_graph_pages("lib", "doc", _nodes(3))
    assert page_count == 3
    assert pages[1]["width"] == 841.0
