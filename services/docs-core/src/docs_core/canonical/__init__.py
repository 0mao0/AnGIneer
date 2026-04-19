"""Docs canonical schema 导出。"""

from .builder import (
    build_canonical_blocks,
    build_canonical_chunks,
    build_canonical_document,
    build_canonical_outlines,
    build_canonical_tables,
)
from .types import (
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
    "build_canonical_blocks",
    "build_canonical_chunks",
    "build_canonical_document",
    "build_canonical_outlines",
    "build_canonical_tables",
]
