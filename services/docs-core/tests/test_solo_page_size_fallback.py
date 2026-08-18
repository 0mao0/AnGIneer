"""load_raw 缺页兜底：middle.json 分块合并缺失时，用 content_list_v2 bbox 反推页面尺寸。"""
import json
from pathlib import Path

from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_raw_dir(tmp: Path) -> Path:
    raw = tmp / "mineru_raw"
    raw.mkdir()
    _write_json(raw / "content_list_v2.json", [
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "page0"}]},
                "bbox": [100, 100, 300, 140],
            },
        ],
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "page1"}]},
                "bbox": [200, 200, 700, 260],
            },
        ],
    ])
    # middle.json 只覆盖第 1 页（模拟分块合并丢失后半段）
    _write_json(raw / "middle.json", {"pdf_info": [
        {
            "page_idx": 0,
            "page_size": [595, 841],
            "preproc_blocks": [],
            "para_blocks": [],
        },
    ]})
    return raw


def test_missing_page_size_falls_back_to_bbox_scale(tmp_path):
    raw = _make_raw_dir(tmp_path)
    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-fallback",
        doc_name="f",
        options={"use_llm": False},
    )
    nodes = result.nodes
    by_page = {int(n["page_idx"]): n for n in nodes}
    p0, p1 = by_page[0], by_page[1]
    # 第 1 页 middle.json 有尺寸（595x841，bbox 未触发 1000 校准），bbox 仍应存在
    assert p0.get("bbox") is not None
    # 第 2 页尺寸缺失：兜底按 1000 归一化坐标系反推
    assert p1.get("page_width") == 1000.0
    assert p1.get("page_height") == 1000.0
    assert p1.get("bbox") == [0.2, 0.2, 0.7, 0.26]
