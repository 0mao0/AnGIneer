"""类型词汇契约：结构层行词汇（MinerU）与 canonical 词汇是两套，边界必须钉死。

2026-09 排查（docs/plan-popo-type-vocabulary.md）：结构层"可续接"等判定集合曾
直接写 canonical 名 `list_item`，而生产行词汇是 `list`（全库 list=6,157 /
list_item=0），集合实际等价于 `{"paragraph"}`，列表能力静默失效无测试可拦。
同时反向钉死：canonical 侧（CanonicalBlock / formula_semantics 解释段候选）**正确**
使用 `list_item`——两条 normalize 路已把 `list`→`list_item`，把 `list` 加进
canonical 判定集合是画蛇添足（本排查曾把 formula_semantics 误判为漂移点）。

任何一侧改词表，本文件对应用例转红。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from docs_core.models.types import BlockType, CanonicalBlock  # noqa: E402
from docs_core.step04_structure.shared import row_vocabulary  # noqa: E402
from docs_core.step04_structure.shared import formula_semantics  # noqa: E402
from docs_core.step05_sqlite_fts.rebuild.canonical_builder import (  # noqa: E402
    normalize_block_type,
)


# ── 结构层行词汇：单一真相源的内容 ──────────────────────────────────────────

def test_row_text_types_are_mineru_vocabulary():
    assert row_vocabulary.ROW_TEXT_TYPES == frozenset({"paragraph", "list"})
    # canonical 别名不得回流结构层行词汇（漂移正是从这两个名字开始的）
    assert "list_item" not in row_vocabulary.ROW_TEXT_TYPES
    assert "text" not in row_vocabulary.ROW_TEXT_TYPES


def test_legacy_alias_types_stay_documentation_only():
    # 若生产数据某天真的开始产出这些别名，本断言提醒你重新评估词表，而不是静默改集合
    assert row_vocabulary.LEGACY_ALIAS_TYPES == frozenset({"text", "list_item"})
    assert not (row_vocabulary.LEGACY_ALIAS_TYPES & row_vocabulary.ROW_TEXT_TYPES)


# ── canonical 侧：映射路把 list 归一为 list_item（④ 误报的根据） ────────────

def test_step05_normalize_maps_mineru_types():
    assert normalize_block_type("list") == "list_item"
    assert normalize_block_type("text") == "paragraph"
    assert normalize_block_type("index") == "toc"


def test_step04_graph_path_aliases_mineru_types():
    aliases = formula_semantics._NODE_TYPE_ALIASES
    assert aliases["list"] == "list_item"
    assert "list" not in formula_semantics._CANONICAL_BLOCK_TYPES


def test_canonical_block_literal_rejects_mineru_row_type():
    # CanonicalBlock 物理上装不进 `list`——所以 canonical 词汇的判定集合
    # 加 `list` 永远不会命中，只会制造"以为修了什么"的假象。
    with pytest.raises(ValidationError):
        CanonicalBlock(block_id="x", doc_id="d", block_type="list")


def test_canonical_block_type_literal_has_no_mineru_names():
    literal = set(BlockType.__args__)  # type: ignore[attr-defined]
    assert "list" not in literal
    assert "text" not in literal
    assert {"paragraph", "list_item"} <= literal


# ── formula_semantics 解释段候选（原"漂移点④"）：行为级反证 ─────────────────

def test_explanation_candidates_are_canonical_text_types():
    types = formula_semantics._CANONICAL_EXPLANATION_TEXT_TYPES
    assert types == frozenset({"paragraph", "list_item"})
    assert types <= formula_semantics._CANONICAL_BLOCK_TYPES


def test_list_item_following_formula_is_picked_up():
    """列表项里的公式参数说明不会被跳过——④ 之所以是误报的行为级证据。"""
    formula = CanonicalBlock(
        block_id="f1", doc_id="d", page_idx=0, block_type="formula",
        text="E = mc^2", reading_order=0, section_path="§1",
    )
    note = CanonicalBlock(
        block_id="li1", doc_id="d", page_idx=0, block_type="list_item",
        text="其中 m 为质量", text_clean="其中 m 为质量",
        reading_order=1, section_path="§1",
    )
    noise = CanonicalBlock(
        block_id="hf1", doc_id="d", page_idx=0, block_type="header_footer",
        text="页脚", text_clean="页脚", reading_order=2, section_path="§1",
    )
    lines = formula_semantics.collect_canonical_explanation_lines(
        formula, [note, noise]
    )
    assert lines == ["其中 m 为质量"]
