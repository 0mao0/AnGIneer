"""步骤五：结构化——solo/popo 引擎 + canonical 构建 + jsonl 落盘。

本包模块较多且互相引用（含 step05 依赖），__init__ 只重导出轻量的 canonical 类型，
其余一律用完整模块路径导入，避免包初始化时形成循环导入。
"""

from .shared.models.types import (
    BoundingBox,
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
)

__all__ = [
    "BoundingBox",
    "CanonicalBlock",
    "CanonicalChunk",
    "CanonicalDocument",
    "CanonicalOutlineNode",
    "CanonicalPage",
    "CanonicalTable",
    "CitationTarget",
]
