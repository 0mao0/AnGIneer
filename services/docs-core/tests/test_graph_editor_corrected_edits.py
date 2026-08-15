from docs_core.step05_sqlite_fts.graph_editor import (
    _apply_content_corrected_edits,
    _build_doc_block_projection_rows,
    _invalidate_edited_formula_semantics,
    _rebuild_graph_projection,
    _sync_related_graph_fields,
)
from docs_core.step05_sqlite_fts.rebuild.graph_rebuilder import build_node_text


def test_apply_content_corrected_edits_writes_corrected_only():
    node = {"plain_text": "旧文本", "math_content": "x=1"}
    applied = _apply_content_corrected_edits(
        node, {"plain_text": "新文本", "math_content": "x=2"}
    )
    assert node["plain_text"] == "旧文本"          # 原始字段不变
    assert node["math_content"] == "x=1"
    assert node["plain_text_corrected"] == "新文本"
    assert node["math_content_corrected"] == "x=2"
    assert node["corrected_by"] == "user"
    assert "corrected_at" in node
    assert applied == ["plain_text_corrected", "math_content_corrected"]


def test_apply_content_corrected_edits_ignores_absent_keys():
    node = {"plain_text": "旧文本"}
    _apply_content_corrected_edits(node, {"footnote": "注"})
    assert "plain_text_corrected" not in node
    assert node["footnote_corrected"] == "注"


def _formula_node(**overrides):
    node = {
        "block_uid": "d:1:1",
        "block_type": "equation_interline",
        "plain_text": "F = ma",
        "math_content": "F = ma",
        "formula_semantics": {"formula_param_count": 1},
    }
    node.update(overrides)
    return node


def test_corrected_edit_invalidates_formula_semantics():
    before = {"nodes": [_formula_node()]}
    after = {"nodes": [_formula_node(plain_text_corrected="F = 2ma")]}
    invalidated = _invalidate_edited_formula_semantics(after, before)
    assert invalidated == ["d:1:1"]
    assert "formula_semantics" not in after["nodes"][0]


def test_untouched_corrected_keeps_semantics():
    node = _formula_node(plain_text_corrected="F = 2ma")
    before = {"nodes": [dict(node)]}
    after = {"nodes": [dict(node)]}
    assert _invalidate_edited_formula_semantics(after, before) == []
    assert "formula_semantics" in after["nodes"][0]


def test_graph_rebuilder_prefers_corrected_text():
    node = {"plain_text": "原始错误文本", "plain_text_corrected": "修正后的文本"}
    assert build_node_text(node) == "修正后的文本"


def test_graph_rebuilder_falls_back_to_original_text():
    node = {"plain_text": "原始文本"}
    assert build_node_text(node) == "原始文本"


def test_sync_related_graph_fields_prefers_plain_text_corrected():
    nodes = [
        {
            "block_uid": "d:1:1",
            "block_type": "caption",
            "plain_text": "旧题注",
            "plain_text_corrected": "新题注",
        },
        {"block_uid": "d:2:1", "block_type": "table", "caption_block_uids": ["d:1:1"]},
    ]
    _sync_related_graph_fields(nodes, "d:1:1", nodes[0])
    assert nodes[1]["caption"] == "新题注"


def test_sync_related_graph_fields_prefers_caption_corrected():
    nodes = [
        {
            "block_uid": "d:1:1",
            "block_type": "table",
            "caption": "旧题注",
            "caption_corrected": "新题注",
        },
        {"block_uid": "d:2:1", "block_type": "image", "caption_block_uids": ["d:1:1"]},
    ]
    _sync_related_graph_fields(nodes, "d:1:1", nodes[0])
    assert nodes[1]["caption"] == "新题注"


def test_sync_related_graph_fields_prefers_footnote_corrected():
    nodes = [
        {
            "block_uid": "d:1:1",
            "block_type": "footnote",
            "plain_text": "旧注",
            "plain_text_corrected": "新注",
        },
        {"block_uid": "d:2:1", "block_type": "table", "footnote_block_uids": ["d:1:1"]},
    ]
    _sync_related_graph_fields(nodes, "d:1:1", nodes[0])
    assert nodes[1]["footnote"] == "新注"


def _graph_with_corrected_rows():
    return {
        "nodes": [
            {
                "block_uid": "d:1:1",
                "block_type": "paragraph",
                "page_idx": 0,
                "block_seq": 0,
                "plain_text": "旧文本",
                "plain_text_corrected": "新文本",
                "table_html": "旧表",
                "table_html_corrected": "新表",
                "math_content": "x=1",
                "math_content_corrected": "x=2",
                "caption": "旧题注",
                "caption_corrected": "新题注",
                "footnote": "旧注",
                "footnote_corrected": "新注",
            }
        ],
        "stats": {
            "base_rows": [{"block_uid": "d:1:1", "doc_id": "d"}],
            "derived_rows": [{"block_uid": "d:1:1", "doc_id": "d"}],
            "index_rows": [{"block_uid": "d:1:1"}],
        },
    }


def test_projection_rows_prefer_corrected():
    base_rows, derived_rows = _build_doc_block_projection_rows(
        "d", _graph_with_corrected_rows()
    )
    assert base_rows[0]["plain_text"] == "新文本"
    assert derived_rows[0]["table_html"] == "新表"
    assert derived_rows[0]["math_content"] == "x=2"


def test_rebuild_graph_projection_stats_rows_prefer_corrected():
    graph = _graph_with_corrected_rows()
    _rebuild_graph_projection(graph)
    base_rows = graph["stats"]["base_rows"]
    assert base_rows[0]["plain_text"] == "新文本"
    assert base_rows[0]["table_html"] == "新表"
    assert base_rows[0]["math_content"] == "x=2"
    assert base_rows[0]["caption"] == "新题注"
    assert base_rows[0]["footnote"] == "新注"


def test_edit_rewrite_uses_faithful_projection(tmp_path, monkeypatch):
    """编辑后 content.md 应为 jsonl 保真投影：标题带 #、页饰不进入正文。"""
    monkeypatch.setenv("KNOWLEDGE_BASE_DIR", str(tmp_path))
    parsed = tmp_path / "libraries" / "lib" / "documents" / "doc" / "parsed"
    parsed.mkdir(parents=True, exist_ok=True)
    (parsed / "content.md").write_text("原文", encoding="utf-8")
    from docs_core.step05_sqlite_fts import graph_editor
    graph = {
        "nodes": [
            {
                "id": 1, "block_uid": "d:0:1", "block_type": "title",
                "derived_level": 1, "page_idx": 0, "block_seq": 1, "plain_text": "第一章",
            },
            {
                "id": 2, "block_uid": "d:0:2", "block_type": "page_header",
                "page_idx": 0, "block_seq": 2, "plain_text": "页眉",
            },
            {
                "id": 3, "block_uid": "d:0:3", "block_type": "paragraph",
                "page_idx": 0, "block_seq": 3, "plain_text": "改过的正文",
            },
        ],
        "edges": [],
    }
    graph_editor._rewrite_markdown_after_graph_change("lib", "doc", graph)
    md = (parsed / "content.md").read_text(encoding="utf-8")
    assert "# 第一章" in md
    assert "改过的正文" in md
    assert "页眉" not in md
