"""步骤四：结构化——MinerU raw → jsonl（块整理 + 层级化 + 语义落盘）。

canonical 类型契约已上移 ``docs_core.models``，本包 __init__ 仅按兼容面
重导出轻量类型，其余一律用完整模块路径导入，避免包初始化形成循环导入。
"""

from docs_core.models.types import (
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
