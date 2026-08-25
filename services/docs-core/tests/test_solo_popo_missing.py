"""Solo 结构在 PoPo 子模块缺失时优雅跳过（不阻断 Solo 构建）。"""
import sys
from unittest.mock import patch

from docs_core.step04_structure.solo2json_pipeline import _apply_popo_signals


def test_apply_popo_signals_skips_when_popo_missing():
    nodes = [{"block_uid": "doc1:0:1", "block_type": "paragraph"}]
    # 模拟 popo 包不存在：sys.modules 中置 None 会令 `import popo.post_processing` 抛 ImportError
    with patch.dict(sys.modules, {"popo": None}):
        out_nodes, stats, candidates = _apply_popo_signals("lib1", "doc1", nodes)
    assert out_nodes == nodes
    assert stats["injection"]["skipped_reason"] == "no_popo_module"
    assert stats["heuristic"]["skipped_reason"] == "no_popo_module"
    assert stats["merge"]["skipped_reason"] == "no_popo_module"
    assert candidates == {}
