"""docs_core ingest/canonical：Canonical 契约（types）与汇聚点（builder）。"""

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
