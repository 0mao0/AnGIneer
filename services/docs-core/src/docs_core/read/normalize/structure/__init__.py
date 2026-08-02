"""结构层（阶段四完成搬迁）：solo 降级后端 + popo 子进程 + 标题校正器。

结构层输出契约（G3）：任何后端（popo mapper / solo 适配器）的职责边界到
``CanonicalBlock`` 为止——``solo.structured_result_to_canonical_blocks`` 与
``popo.popo_mapper.po_po_blocks_to_canonical`` 是两条后端的统一出口。
"""
from .solo import (
    RawFilesStructureBuilder,
    StructuredResult,
    build_graph_from_rawfiles,
    build_structured_from_rawfiles,
    collect_media_related_block_refs,
    structured_result_to_canonical_blocks,
)
from .title_level_refiner import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    estimate_backend_level_confidence,
    llm_refine_title_levels,
    resolve_title_level_refinement,
)

__all__ = [
    "DEFAULT_CONFIDENCE_THRESHOLD",
    "RawFilesStructureBuilder",
    "StructuredResult",
    "build_graph_from_rawfiles",
    "build_structured_from_rawfiles",
    "collect_media_related_block_refs",
    "estimate_backend_level_confidence",
    "llm_refine_title_levels",
    "resolve_title_level_refinement",
    "structured_result_to_canonical_blocks",
]
