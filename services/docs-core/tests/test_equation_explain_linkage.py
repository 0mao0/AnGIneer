"""公式解释段关联：LaTeX 残渣延续判定 + explanation_uids 回写兜底测试。"""
import json

from docs_core.step04_structure.shared.formula_semantics import (
    enrich_graph_nodes_formula_semantics,
)
from docs_core.step04_structure.solo_engine import is_equation_explain_continuation


# ---------- Task A: is_equation_explain_continuation ----------

def test_continuation_matches_latex_residue_with_spaces():
    # MinerU 的 LaTeX 残渣带空格（K _ { t }、t _ { 2 }），以及 \pmb 命令包裹
    assert is_equation_explain_continuation("K _ { t }——时间富裕系数，取1.1~1.3;")
    assert is_equation_explain_continuation("t _ { 2 }艘船舶在港内转头的时间(h);")
    assert is_equation_explain_continuation("\\pmb { \\ t } _ { 1 }每潮次船舶通过航道的持续时间(h)")
    assert is_equation_explain_continuation("A——航迹带宽度(m)")


def test_continuation_matches_bullet_and_plain_symbol():
    assert is_equation_explain_continuation("•K——系数")
    assert is_equation_explain_continuation("式中 t_s——每潮次船舶乘潮进出港所需的持续时间(h)")


def test_continuation_rejects_heading_and_body():
    # 编号开头（正文条款）与普通中文正文不应误判为公式解释延续
    assert not is_equation_explain_continuation("6.2.8.2 单一潮位站的乘潮水位应按现行行业标准统计")
    assert not is_equation_explain_continuation("港口平面布置应结合地形地质条件综合确定")
    assert not is_equation_explain_continuation("")


# ---------- Task B: explanation_uids 回写兜底 ----------

def _graph_formula_with_partial_explanation():
    """公式只关联第 1 段解释，后续 4 段靠重定位补充（模拟 6.2.8 现状）。"""
    nodes = [
        {
            "id": "doc-t:0:1",
            "block_uid": "doc-t:0:1",
            "block_type": "title",
            "page_idx": 0,
            "block_seq": 1,
            "plain_text": "6.2.8 乘潮水位",
            "title_path": "doc-t:0:1",
            "bbox": [0.0, 0.0, 0.5, 0.05],
        },
        {
            "id": "doc-t:0:2",
            "block_uid": "doc-t:0:2",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 2,
            "plain_text": "6.2.8.1 每潮次船舶乘潮进出港所需的持续时间可按式(6.2.8)确定",
            "title_path": "doc-t:0:1",
            "bbox": [0.0, 0.06, 0.9, 0.10],
        },
        {
            "id": "doc-t:0:3",
            "block_uid": "doc-t:0:3",
            "block_type": "equation_interline",
            "page_idx": 0,
            "block_seq": 3,
            "plain_text": "t _ { \\mathrm { s } } = K _ { \\mathrm { t } } \\big ( t _ { 1 } + t _ { 2 } + t _ { 3 } \\big )\\tag{6.2.8}",
            "math_content": "t _ { \\mathrm { s } } = K _ { \\mathrm { t } } \\big ( t _ { 1 } + t _ { 2 } + t _ { 3 } \\big )\\tag{6.2.8}",
            "title_path": "doc-t:0:1",
            "bbox": [0.1, 0.11, 0.6, 0.13],
            "equation_number_bbox": [0.75, 0.11, 0.85, 0.13],
            "explanation_uids": ["doc-t:0:4"],
        },
        {
            "id": "doc-t:0:4",
            "block_uid": "doc-t:0:4",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 4,
            "plain_text": "式中 \\pmb { t _ { \\check { \\mathbf { s } } } }——每潮次船舶乘潮进出港所需的持续时间(h)",
            "title_path": "doc-t:0:1",
            "bbox": [0.0, 0.14, 0.6, 0.16],
        },
        {
            "id": "doc-t:0:5",
            "block_uid": "doc-t:0:5",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 5,
            "plain_text": "K _ { t }——时间富裕系数，取1.1~1.3",
            "title_path": "doc-t:0:1",
            "bbox": [0.05, 0.17, 0.5, 0.19],
        },
        {
            "id": "doc-t:0:6",
            "block_uid": "doc-t:0:6",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 6,
            "plain_text": "t _ { 2 }艘船舶在港内转头的时间(h)",
            "title_path": "doc-t:0:1",
            "bbox": [0.05, 0.20, 0.5, 0.22],
        },
        {
            "id": "doc-t:0:7",
            "block_uid": "doc-t:0:7",
            "block_type": "paragraph",
            "page_idx": 0,
            "block_seq": 7,
            "plain_text": "t _ { 3 }艘船舶靠离码头的时间(h)",
            "title_path": "doc-t:0:1",
            "bbox": [0.05, 0.23, 0.5, 0.25],
        },
    ]
    return nodes


def test_enrich_backfills_explanation_uids_with_rederived_blocks():
    nodes = _graph_formula_with_partial_explanation()
    updated, stats = enrich_graph_nodes_formula_semantics(nodes, use_llm=False)
    formula = next(n for n in updated if n.get("block_type") == "equation_interline")
    uids = formula.get("explanation_uids") or []
    # 原关联 doc-t:0:4 保留，重定位补充 0:5/0:6/0:7
    assert "doc-t:0:4" in uids
    assert "doc-t:0:5" in uids
    assert "doc-t:0:6" in uids
    assert "doc-t:0:7" in uids
    # explanation_lines 与关联对齐（4 段文本）
    assert len(formula["formula_semantics"]["explanation_lines"]) == 4
    assert stats["enriched"] == 1
