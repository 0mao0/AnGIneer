"""hybrid-engine 输出格式兼容：model.json 裸列表 + middle.json page_size 兜底。"""
import json
from pathlib import Path

from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_hybrid_raw_dir(tmp: Path) -> Path:
    raw = tmp / "mineru_raw"
    raw.mkdir()
    _write_json(raw / "content_list_v2.json", [
        [
            {
                "type": "paragraph",
                "content": {"paragraph_content": [{"type": "text", "content": "hello"}]},
                "bbox": [100, 100, 300, 140],
            },
            {
                "type": "table",
                "content": {
                    "table_caption": [{"type": "text", "content": "表 1 标题"}],
                    "html": "<table><tr><td>a</td></tr></table>",
                },
                "bbox": [100, 200, 800, 700],
            },
            {
                "type": "page_number",
                "content": {"page_number_content": [{"type": "text", "content": "1"}]},
                "bbox": [900, 950, 960, 980],
            },
        ]
    ])
    _write_json(raw / "model.json", [[
        {"type": "header", "bbox": [0.64, 0.067, 0.903, 0.084], "content": "header"},
        {"type": "image_caption", "bbox": [0.1, 0.15, 0.3, 0.17], "content": "表 1 标题"},
        {"type": "table", "bbox": [0.1, 0.2, 0.8, 0.7], "content": "<table/>"},
    ]])
    _write_json(raw / "middle.json", {"pdf_info": [
        {
            "page_idx": 0,
            "page_size": [612, 825],
            "preproc_blocks": [],
            "para_blocks": [
                {"type": "text", "lines": [{"spans": [{"content": "hello"}]}]},
                {
                    "type": "table",
                    "bbox": [110, 83, 552, 744],
                    "blocks": [
                        {
                            "type": "table_caption",
                            "bbox": [93, 251, 108, 579],
                            "lines": [{"spans": [{"content": "表 1 标题"}]}],
                        },
                        {"type": "table_body", "bbox": [110, 83, 552, 744]},
                    ],
                },
            ],
        },
    ]})
    return raw


def test_hybrid_middle_page_size_fallback_normalizes_bbox(tmp_path):
    raw = _make_hybrid_raw_dir(tmp_path)
    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-hybrid",
        doc_name="h",
        options={"use_llm": False},
    )
    nodes = result.nodes
    para = next(n for n in nodes if n.get("block_type") == "paragraph")
    table = next(n for n in nodes if n.get("block_type") == "table")
    assert para.get("page_width") == 1000.0
    assert para.get("bbox") == [0.1, 0.1, 0.3, 0.14]
    assert table.get("bbox") == [0.1, 0.2, 0.8, 0.7]
    assert table.get("table_html")


def test_hybrid_model_caption_bbox_kept(tmp_path):
    raw = _make_hybrid_raw_dir(tmp_path)
    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-hybrid",
        doc_name="h",
        options={"use_llm": False},
    )
    table = next(n for n in result.nodes if n.get("block_type") == "table")
    cj = table.get("content_json") or {}
    assert cj.get("table_caption") == [{"type": "text", "content": "表 1 标题"}]
    assert table.get("caption_bboxes") is not None
    x0, y0, x1, y1 = table["caption_bboxes"][0]
    assert abs(x0 - 93 / 612) < 0.001
    assert abs(y0 - 251 / 825) < 0.001
    assert abs(x1 - 108 / 612) < 0.001
    assert abs(y1 - 579 / 825) < 0.001


def test_hybrid_formula_number_bbox_fallback(tmp_path):
    raw = _make_hybrid_raw_dir(tmp_path)
    content_path = raw / "content_list_v2.json"
    blocks = json.loads(content_path.read_text(encoding="utf-8"))
    blocks[0].append({
        "type": "equation_interline",
        "content": {
            "math_content": r"W = A + 2 c\tag{6.4.2-1}",
            "math_type": "latex",
        },
        "bbox": [100, 400, 500, 450],
    })
    content_path.write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")

    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-hybrid-formula",
        doc_name="h",
        options={"use_llm": False},
    )
    formula = next(
        node for node in result.nodes
        if node.get("block_type") == "equation_interline"
    )
    bbox = formula.get("equation_number_bbox")
    assert bbox is not None
    assert len(bbox) == 4
    assert bbox[2] > 0.8
    assert bbox[2] < 1.0
    assert bbox[0] < bbox[2]
    assert bbox[1] < bbox[3]
    assert formula.get("formula_number") == "6.4.2-1"
    assert formula.get("formula_body") == "W = A + 2 c"


def test_page_last_text_ends_cut_ignores_comma_and_enumeration_comma():
    """顿号/逗号不是句末标点：页末断在“、”或“,”仍视为续文证据。"""
    from docs_core.step04_structure.solo_engine import _page_last_text_ends_cut

    def middle_with_last(text):
        return {"pdf_info": [{"preproc_blocks": [
            {"type": "text", "lines": [{"spans": [{"content": "前面完整段落。"}]}]},
            {"type": "text", "lines": [{"spans": [{"content": text}]}]},
        ]}]}

    assert _page_last_text_ends_cut(middle_with_last("水域开阔、风、"), 0) is True
    assert _page_last_text_ends_cut(middle_with_last("便于船舶进出航道的水域,并应符合下列"), 0) is True
    assert _page_last_text_ends_cut(middle_with_last("完整句子结束。"), 0) is False
