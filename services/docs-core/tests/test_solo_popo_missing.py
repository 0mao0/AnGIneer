"""Solo 结构在 PoPo 子模块缺失时优雅跳过（不阻断 Solo 构建）。"""
import sys
from unittest.mock import patch

from docs_core.step04_structure.solo2json_pipeline import _apply_popo_signals


def test_apply_popo_signals_skips_when_popo_missing():
    nodes = [{"block_uid": "doc1:0:1", "block_type": "paragraph"}]
    # 模拟 popo 子模块不存在：把相关模块在 sys.modules 中置 None，令后续 import 抛 ImportError
    # （含已加载缓存——全量测试时 step04 popo 子模块可能已被其他用例真实导入）
    poopo_modules = {
        "popo",
        "popo.post_processing",
        "docs_core.step04_structure.popo",
        "docs_core.step04_structure.popo.popo_signal_aligner",
        "docs_core.step04_structure.popo.popo_block_merger",
        "docs_core.step04_structure.popo.popo_signal_injector",
        "docs_core.step04_structure.popo.popo_signal_level_fusion",
    }
    with patch.dict(sys.modules, {name: None for name in poopo_modules}):
        out_nodes, stats, candidates = _apply_popo_signals("lib1", "doc1", nodes)
    assert out_nodes == nodes
    assert stats["injection"]["skipped_reason"] == "no_popo_module"
    assert stats["heuristic"]["skipped_reason"] == "no_popo_module"
    assert stats["merge"]["skipped_reason"] == "no_popo_module"
    assert candidates == {}
