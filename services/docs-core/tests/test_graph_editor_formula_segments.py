"""graph_editor 公式条目优先读 jsonl 契约测试。"""
from docs_core.step05_sqlite_fts.graph_editor import _build_structured_segment_items_from_graph


def _graph(nodes):
    return {"nodes": nodes, "edges": []}


def test_formula_items_prefer_jsonl_contract() -> None:
    contract = {
        "formula_text": "W = A + 2c",
        "formula_number": "6.4.2-1",
        "formula_params": [
            {"symbol": "W", "description": "航道通航宽度(m)", "unit": "m",
             "reference_hint": None, "confidence": 0.99, "extracted_by": "llm"}
        ],
        "formula_param_count": 1,
        "formula_summary": "公式(6.4.2-1) W = A + 2c；包含 1 个参数：W",
        "llm_status": "ok",
        "explanation_lines": ["式中 W——航道通航宽度(m)"],
    }
    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "plain_text": "W = A + 2c",
            "math_content": "W = A + 2c", "formula_semantics": dict(contract),
        }
    ]
    items = _build_structured_segment_items_from_graph(_graph(nodes))
    formula_item = next(it for it in items if it.get("item_type") == "equation_interline")
    meta = formula_item["meta"]
    assert meta["formula_number"] == "6.4.2-1"
    assert meta["formula_llm_status"] == "ok"
    assert meta["formula_param_count"] == 1
    summary_item = next(it for it in items if it.get("item_type") == "formula_summary")
    assert summary_item["content"] == contract["formula_summary"]
    param_item = next(it for it in items if it.get("item_type") == "formula_param")
    assert param_item["title"] == "W"
    assert param_item["meta"]["extracted_by"] == "llm"


def test_formula_items_fallback_when_no_contract() -> None:
    nodes = [
        {
            "block_uid": "d:1:1", "block_type": "equation_interline",
            "page_idx": 1, "block_seq": 1, "plain_text": "F = ma",
            "math_content": "F = ma",
        }
    ]
    items = _build_structured_segment_items_from_graph(_graph(nodes))
    formula_item = next(it for it in items if it.get("item_type") == "equation_interline")
    assert formula_item["meta"]["formula_llm_status"] in ("disabled", "not_needed")
