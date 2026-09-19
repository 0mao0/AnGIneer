"""PoPo 续接/续表判定的行词汇规则（docs/plan-popo-type-vocabulary.md 步骤 2a/2b/3）。

钉三件事：
1. contd 校验接受 `list`↔`list`（生产行词汇 list=6157 / list_item=0，旧集合写
   canonical 名导致列表续接 100% 被拒）；
2. 两端**不同型**（paragraph↔list）一律拒——popo_block_merger._merge_text_fragments
   任一侧带 paragraph_content 即走文本拼接、另一侧 list_items 被 flatten 丢弃；
3. 续表标记扫描范围含 `list`（标记写进列表块时旧集合缺 list 会漏检）。
"""

from __future__ import annotations

from docs_core.step04_structure.popo import popo_signal_injector as injector_mod
from docs_core.step04_structure.popo import popo_table_continuation as table_cont_mod
from docs_core.step04_structure.popo.popo_signal_injector import validate_instruction
from docs_core.step04_structure.popo.popo_table_continuation import (
    _MARKER_SCAN_TYPES,
    _continuation_marker_before,
)
from docs_core.step04_structure.shared.row_vocabulary import ROW_TEXT_TYPES


def _nodes(*specs):
    return {
        uid: {
            "block_uid": uid, "block_type": btype,
            "page_idx": page, "block_seq": seq, "plain_text": text,
        }
        for uid, btype, page, seq, text in specs
    }


# ── 2a/3：contd 类型校验 ──────────────────────────────────────────────

def test_contd_single_source_of_truth() -> None:
    """injector 的续接类型集合必须直接引用 ROW_TEXT_TYPES（单一真相源）。"""
    assert injector_mod._CONTINUABLE_TYPES is ROW_TEXT_TYPES
    assert "list" in injector_mod._CONTINUABLE_TYPES


def test_contd_list_to_list_accepted() -> None:
    nodes_by_uid = _nodes(
        ("d:0:1", "list", 0, 1, "列表项前半"),
        ("d:1:1", "list", 1, 1, "列表项后半"),
    )
    ok, reason = validate_instruction(
        nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:1:1"}
    )
    assert ok, reason


def test_contd_paragraph_to_paragraph_still_accepted() -> None:
    nodes_by_uid = _nodes(
        ("d:0:1", "paragraph", 0, 1, "段落前半"),
        ("d:1:1", "paragraph", 1, 1, "段落后半"),
    )
    ok, reason = validate_instruction(
        nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:1:1"}
    )
    assert ok, reason


def test_contd_mixed_paragraph_list_rejected_same_type() -> None:
    """两端不同型拒收：防 _merge_text_fragments 把 list_items flatten 掉。"""
    for src, tgt in (("paragraph", "list"), ("list", "paragraph")):
        nodes_by_uid = _nodes(
            ("d:0:1", src, 0, 1, "前半"),
            ("d:1:1", tgt, 1, 1, "后半"),
        )
        ok, reason = validate_instruction(
            nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:1:1"}
        )
        assert not ok, f"{src}->{tgt} 应被拒"
        assert "不同型" in reason


def test_contd_canonical_names_rejected() -> None:
    """canonical 名（list_item/text）不在行词汇——出现即词汇漂移，拒收。"""
    for btype in ("list_item", "text"):
        nodes_by_uid = _nodes(
            ("d:0:1", btype, 0, 1, "前半"),
            ("d:1:1", btype, 1, 1, "后半"),
        )
        ok, reason = validate_instruction(
            nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:1:1"}
        )
        assert not ok, f"{btype} 不应通过行词汇校验"
        assert "类型不兼容" in reason


def test_contd_list_crossing_title_still_rejected() -> None:
    """放开 list 后「不跨标题」兜底依然生效（title 不在可续接集合、中间标题扫描双保险）。"""
    nodes_by_uid = _nodes(
        ("d:0:1", "list", 0, 1, "列表前半"),
        ("d:0:2", "title", 0, 2, "新章节"),
        ("d:0:3", "list", 0, 3, "列表后半"),
    )
    ok, reason = validate_instruction(
        nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:0:3"}
    )
    assert not ok
    assert "跨越标题" in reason


def test_contd_rule_flips_when_list_removed(monkeypatch) -> None:
    """敏感度：把 list 从可续接集合去掉，list↔list 用例必须转红（计划校核清单）。"""
    monkeypatch.setattr(injector_mod, "_CONTINUABLE_TYPES", frozenset({"paragraph"}))
    nodes_by_uid = _nodes(
        ("d:0:1", "list", 0, 1, "列表项前半"),
        ("d:1:1", "list", 1, 1, "列表项后半"),
    )
    ok, reason = validate_instruction(
        nodes_by_uid, {"kind": "contd", "source_uid": "d:0:1", "target_uid": "d:1:1"}
    )
    assert not ok
    assert "类型不兼容" in reason


# ── 2b：续表标记扫描范围 ──────────────────────────────────────────────

def test_marker_scan_covers_list_block() -> None:
    assert "list" in _MARKER_SCAN_TYPES
    assert ROW_TEXT_TYPES <= _MARKER_SCAN_TYPES


def test_marker_before_list_block_detected() -> None:
    ordered = _nodes(
        ("d:1:1", "list", 1, 1, "续表A.0.2-2"),
        ("d:1:2", "table", 1, 2, ""),
    ).values()
    assert _continuation_marker_before(list(ordered), 1, 2) is True


def test_marker_before_out_of_scan_type_ignored() -> None:
    """page_footer 不在扫描范围：页脚里的"续"字不算续表标记。"""
    ordered = _nodes(
        ("d:1:1", "page_footer", 1, 1, "续表A.0.2-2"),
        ("d:1:2", "table", 1, 2, ""),
    ).values()
    assert _continuation_marker_before(list(ordered), 1, 2) is False


def test_marker_rule_flips_when_list_removed(monkeypatch) -> None:
    monkeypatch.setattr(table_cont_mod, "_MARKER_SCAN_TYPES", frozenset({"paragraph", "text", "title"}))
    ordered = _nodes(
        ("d:1:1", "list", 1, 1, "续表A.0.2-2"),
        ("d:1:2", "table", 1, 2, ""),
    ).values()
    assert _continuation_marker_before(list(ordered), 1, 2) is False
