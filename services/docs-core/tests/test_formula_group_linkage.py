"""solo_engine 公式组解释段关联测试。"""
import json

from fixtures.popo_fixtures import build_canonical_from_solo_jsonl, content_list_block


def _formula_group_nodes(tmp_path):
    pages = [
        [
            content_list_block("title", "6.4 航道尺度", level=1),
            content_list_block("equation_interline", "W = A + 2c", math="W = A + 2c"),
            content_list_block("paragraph", "双线航道"),
            content_list_block("equation_interline", "W = 2A + b + 2c", math="W = 2A + b + 2c"),
            content_list_block("equation_interline", "A = n(L sinγ + B)", math="A = n(L sinγ + B)"),
            content_list_block("paragraph", "式中 W——航道通航宽度(m)；"),
            content_list_block("paragraph", "A——航迹带宽度(m)；"),
            content_list_block("paragraph", "c——船舶与航道底边线间的富裕宽度(m)。"),
        ],
    ]
    build_canonical_from_solo_jsonl("doc-1", pages, tmp_path)
    with open(tmp_path / "doc_blocks_graph.jsonl", encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_shared_explanation_block_attaches_to_all_group_formulas(tmp_path) -> None:
    nodes = _formula_group_nodes(tmp_path)
    formulas = [n for n in nodes if n.get("block_type") == "equation_interline"]
    assert len(formulas) == 3
    for formula in formulas:
        assert len(formula.get("explanation_uids") or []) == 3, formula.get("block_uid")
