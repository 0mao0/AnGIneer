"""graph_editor 编辑后公式语义失效测试。"""
from docs_core.step05_sqlite_fts.graph_editor import _invalidate_edited_formula_semantics


def test_invalidate_edited_formula_semantics_clears_changed_formula() -> None:
    before = {
        "nodes": [
            {
                "block_uid": "d:1:1", "block_type": "equation_interline",
                "plain_text": "F = ma", "math_content": "F = ma",
                "formula_semantics": {"formula_text": "F = ma", "formula_param_count": 1},
            }
        ]
    }
    after = {
        "nodes": [
            {
                "block_uid": "d:1:1", "block_type": "equation_interline",
                "plain_text": "F = 2ma", "math_content": "F = 2ma",
                "formula_semantics": {"formula_text": "F = ma", "formula_param_count": 1},
            }
        ]
    }
    invalidated = _invalidate_edited_formula_semantics(after, before)
    assert invalidated == ["d:1:1"]
    assert "formula_semantics" not in after["nodes"][0]


def test_invalidate_keeps_untouched_formula() -> None:
    node = {
        "block_uid": "d:1:1", "block_type": "equation_interline",
        "plain_text": "F = ma", "math_content": "F = ma",
        "formula_semantics": {"formula_param_count": 1},
    }
    before = {"nodes": [dict(node)]}
    after = {"nodes": [dict(node)]}
    assert _invalidate_edited_formula_semantics(after, before) == []
    assert "formula_semantics" in after["nodes"][0]
