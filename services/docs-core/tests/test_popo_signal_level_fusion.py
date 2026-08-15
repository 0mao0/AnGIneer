"""Phase 8：PoPo 层级候选信号映射（enriched level + document_tree 结构级别）。"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from docs_core.step04_structure.popo.popo_signal_aligner import align_popo_blocks
from docs_core.step04_structure.popo.popo_signal_level_fusion import (
    build_popo_level_map,
    build_popo_tree_level_map,
)


REPO_ROOT = Path(__file__).resolve().parents[3]
KB = REPO_ROOT / "data" / "knowledge_base" / "libraries" / "default" / "documents"
HAIGANG1 = "doc-12f45ca9"


def test_build_popo_level_map_maps_only_title_blocks() -> None:
    alignment = SimpleNamespace(solo_block_uid_map={"s1": "d:0:1"})
    enriched = [
        {"source_id": "s1", "type": "title", "level": 3},
        {"source_id": "s2", "type": "paragraph", "level": 2},
        {"source_id": "s3", "type": "title", "level": 0},
        {"source_id": "s4", "type": "title", "level": None},
    ]
    level_map = build_popo_level_map(enriched, alignment)
    assert level_map == {"s1": 3}


@pytest.mark.skipif(not (KB / HAIGANG1 / "parsed").exists(), reason="真实数据目录缺失")
def test_tree_level_map_maps_title_blocks_via_alignment() -> None:
    parsed = KB / HAIGANG1 / "parsed"
    tree = json.loads((parsed / "popo" / "document_tree.json").read_text(encoding="utf-8"))
    middle = json.loads((parsed / "mineru_raw" / "middle.json").read_text(encoding="utf-8"))
    enriched = json.loads((parsed / "popo" / "enriched_blocks.json").read_text(encoding="utf-8"))
    alignment = align_popo_blocks(HAIGANG1, middle, enriched)
    tree_levels = build_popo_tree_level_map(tree, enriched, alignment)
    assert tree_levels, "树应至少映射出一个 title 块"
    for uid, level in tree_levels.items():
        assert isinstance(level, int) and level >= 1
