# 识别置信度透传：type_recognition_score / text_recognition_score 契约测试
import json
from pathlib import Path

from docs_core.step04_structure.solo_engine import _model_type_recognition_map
from docs_core.step04_structure.solo_engine import (
    _derive_formula_number_bbox_map,
    _extract_formula_tag,
    _middle_text_recognition_scores,
    _nearest_type_score,
    _strip_formula_tag,
)
from docs_core.step04_structure.solo_engine import build_structured_from_rawfiles


def _sample_model_payload():
    return [{
        "page_info": {"page_no": 0, "width": 1000, "height": 1000},
        "layout_dets": [
            {"label": "text", "score": 0.95, "bbox": [100, 100, 200, 150], "index": 0},
            {"label": "display_formula", "score": 0.92, "bbox": [300, 300, 500, 400], "index": 1},
        ],
    }]


def test_model_type_recognition_map_normalizes_bbox():
    m = _model_type_recognition_map(_sample_model_payload())
    items = m[0]
    assert items[0] == ("text", 0.95, [0.1, 0.1, 0.2, 0.15])
    assert items[1] == ("display_formula", 0.92, [0.3, 0.3, 0.5, 0.4])


def test_model_type_recognition_map_skips_invalid_dets():
    payload = [{
        "page_info": {"page_no": 0, "width": 1000, "height": 1000},
        "layout_dets": [
            {"label": "text", "bbox": [0, 0, 1, 1]},          # 无 score，跳过
            {"label": "text", "score": "oops", "bbox": [0, 0, 1, 1]},  # score 非数值，保留为 None
            {"label": "text", "score": 0.8, "bbox": [0, 0, 1, 1]},
        ],
    }]
    items = _model_type_recognition_map(payload)[0]
    assert len(items) == 2
    assert items[0][1] is None
    assert items[1][1] == 0.8


def test_model_type_recognition_map_missing_payload():
    assert _model_type_recognition_map([]) == {}
    assert _model_type_recognition_map({"not_pdf": True}) == {}


def test_model_type_recognition_map_hybrid_list_pages():
    """hybrid-engine 的 model.json 是裸列表：type 当 label，归一化 bbox 直接透传。"""
    payload = [[
        {"type": "header", "bbox": [0.64, 0.067, 0.903, 0.084], "content": "header"},
        {"type": "table", "bbox": [0.181, 0.101, 0.902, 0.902], "content": "<table/>"},
        {"type": "image_caption", "bbox": [0.152, 0.305, 0.178, 0.702], "content": "caption"},
    ]]
    m = _model_type_recognition_map(payload)
    assert m[0] == [
        ("header", None, [0.64, 0.067, 0.903, 0.084]),
        ("table", None, [0.181, 0.101, 0.902, 0.902]),
        ("image_caption", None, [0.152, 0.305, 0.178, 0.702]),
    ]


def test_model_formula_number_map_hybrid_list_pages():
    from docs_core.step04_structure.solo_engine import _model_formula_number_map

    payload = [[
        {"type": "text", "bbox": [0.1, 0.1, 0.2, 0.2]},
        {"type": "display_formula", "bbox": [0.3, 0.3, 0.5, 0.4]},
        {"type": "formula_number", "bbox": [0.6, 0.1, 0.7, 0.15]},
    ]]
    m = _model_formula_number_map(payload)
    assert m[0] == [[0.6, 0.1, 0.7, 0.15]]


def test_extract_formula_tag():
    assert _extract_formula_tag(r"W = A + 2 c\tag{6.4.2-1}") == "6.4.2-1"
    assert _extract_formula_tag(r"x = 1\tag*{6.2.8}") == "6.2.8"
    assert _extract_formula_tag("no tag here") is None
    assert _extract_formula_tag(None) is None


def test_strip_formula_tag():
    assert _strip_formula_tag(r"W = A + 2 c\tag{6.4.2-1}") == "W = A + 2 c"
    assert _strip_formula_tag(r"x = 1\tag*{6.2.8}") == "x = 1"
    assert _strip_formula_tag("no tag here") == "no tag here"
    assert _strip_formula_tag(None) is None


def test_derive_formula_number_bbox_map_hybrid():
    parsed_blocks = [[
        {
            "type": "equation_interline",
            "content": {"math_content": r"W = A + 2 c\tag{6.4.2-1}"},
            "bbox": [100, 200, 500, 300],
        },
    ]]
    middle_payload = {
        "pdf_info": [{
            "page_idx": 0,
            "page_size": [612, 825],
            "para_blocks": [
                {"type": "text", "bbox": [50, 50, 520, 80]},
            ],
        }],
    }
    page_size_map = {0: (1000.0, 1000.0)}
    m = _derive_formula_number_bbox_map(parsed_blocks, middle_payload, page_size_map)
    assert 0 in m
    assert len(m[0]) == 1
    bbox = m[0][0]
    assert abs(bbox[2] - (520 - 3.5) / 612) < 1e-4
    assert abs((bbox[2] - bbox[0]) - (9 * 6.2) / 612) < 1e-4
    assert abs((bbox[3] - bbox[1]) - 13.0 / 825) < 1e-4
    assert 0.24 < bbox[1] < 0.26


def test_derive_formula_number_bbox_map_ignores_untagged_equations():
    parsed_blocks = [[
        {
            "type": "equation_interline",
            "content": {"math_content": "x = 1"},
            "bbox": [100, 200, 300, 250],
        },
    ]]
    middle_payload = {
        "pdf_info": [{
            "page_idx": 0,
            "page_size": [612, 825],
            "para_blocks": [{"type": "text", "bbox": [50, 50, 520, 80]}],
        }],
    }
    m = _derive_formula_number_bbox_map(parsed_blocks, middle_payload, {0: (1000.0, 1000.0)})
    assert m == {}


def _sample_middle_payload():
    return {
        "pdf_info": [{
            "page_idx": 0,
            "para_blocks": [
                {"type": "text", "lines": [{"spans": [{"score": 0.9}, {"score": 0.7}]}]},
                {"type": "image", "lines": []},
                {"type": "text", "lines": [{"spans": [{"score": 1.0}]}]},
            ],
        }]
    }


def test_middle_text_recognition_scores_takes_min_per_block():
    s = _middle_text_recognition_scores(_sample_middle_payload())
    assert s[0] == [0.7, None, 1.0]


def test_middle_text_recognition_scores_skips_bad_spans():
    payload = {
        "pdf_info": [{
            "page_idx": 0,
            "para_blocks": [
                {"type": "text", "lines": [{"spans": [{"score": "x"}, {"score": 0.88}]}]},
            ],
        }]
    }
    assert _middle_text_recognition_scores(payload)[0] == [0.88]


def test_nearest_type_score():
    items = [
        ("text", 0.9, [0.0, 0.0, 0.1, 0.1]),
        ("display_formula", 0.8, [0.5, 0.5, 0.7, 0.7]),
    ]
    assert _nearest_type_score(items, 0.05, 0.05, 0.06, 0.06) == 0.9
    assert _nearest_type_score(items, 0.55, 0.55, 0.6, 0.6) == 0.8


def test_nearest_type_score_none_when_far_or_no_valid_score():
    items = [("text", 0.9, [0.0, 0.0, 0.1, 0.1])]
    assert _nearest_type_score(items, 0.8, 0.8, 0.9, 0.9) is None
    assert _nearest_type_score([("text", None, [0.0, 0.0, 0.1, 0.1])], 0.05, 0.05, 0.06, 0.06) is None
    assert _nearest_type_score([], 0.05, 0.05, 0.06, 0.06) is None


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _make_raw_dir(tmp: Path) -> Path:
    raw = tmp / "mineru_raw"
    raw.mkdir()
    _write_json(raw / "content_list_v2.json", [
        [
            {"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "hello"}]}, "bbox": [100, 100, 300, 140]},
            {"type": "equation_interline", "content": {"math_content": "x=1"}, "bbox": [100, 200, 400, 240]},
            {"type": "page_number", "content": {}, "bbox": [900, 950, 960, 980]},
        ]
    ])
    _write_json(raw / "model.json", [{
        "page_info": {"page_no": 0, "width": 1000, "height": 1000},
        "layout_dets": [
            {"label": "text", "score": 0.96, "bbox": [100, 100, 300, 140], "index": 0},
            {"label": "display_formula", "score": 0.91, "bbox": [100, 200, 400, 240], "index": 1},
            {"label": "number", "score": 0.88, "bbox": [900, 950, 960, 980], "index": 2},
        ],
    }])
    _write_json(raw / "middle.json", {"pdf_info": [{
        "page_idx": 0,
        "para_blocks": [
            {"type": "paragraph", "lines": [{"spans": [{"score": 0.93}]}]},
            {"type": "equation_interline", "lines": []},
        ],
    }]})
    return raw


def test_nodes_carry_recognition_scores(tmp_path):
    raw = _make_raw_dir(tmp_path)
    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-t",
        doc_name="t",
        options={"use_llm": False},
    )
    nodes = result.nodes
    text_node = next(n for n in nodes if n.get("plain_text") == "hello")
    formula_node = next(n for n in nodes if n.get("math_content") == "x=1")
    assert text_node["type_recognition_score"] == 0.96
    assert text_node["text_recognition_score"] == 0.93
    assert formula_node["type_recognition_score"] == 0.91
    assert formula_node["text_recognition_score"] is None


def test_nodes_missing_scores_when_no_raw_payload(tmp_path):
    raw = tmp_path / "mineru_raw"
    raw.mkdir()
    _write_json(raw / "content_list_v2.json", [
        [{"type": "paragraph", "content": {"paragraph_content": [{"type": "text", "content": "hi"}]}, "bbox": [100, 100, 200, 140]}]
    ])
    _write_json(raw / "model.json", [])
    _write_json(raw / "middle.json", {})
    result = build_structured_from_rawfiles(
        parsed_dir=raw.parent,
        doc_id="doc-t",
        doc_name="t",
        options={"use_llm": False},
    )
    node = result.nodes[0]
    assert node.get("type_recognition_score") is None
    assert node.get("text_recognition_score") is None
