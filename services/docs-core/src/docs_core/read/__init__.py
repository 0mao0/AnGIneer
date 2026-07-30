"""docs_core read pipeline — 文档解析：convert / extract / normalize / organize"""

from .extract import MinerUParser, mineru_parser
from .normalize import (
    RawFilesStructureBuilder,
    StructuredResult,
    build_graph_from_rawfiles,
    build_structured_from_rawfiles,
    build_table_representations,
    classify_table,
    extract_table_features,
)
from .organize import (
    BoundingBox,
    CanonicalBlock,
    CanonicalChunk,
    CanonicalDocument,
    CanonicalOutlineNode,
    CanonicalPage,
    CanonicalTable,
    CitationTarget,
    build_canonical_blocks,
    build_canonical_chunks,
    build_canonical_document,
    build_canonical_outlines,
    build_canonical_tables,
)
from docs_core.write.store import FileStorage, build_structured_index_for_doc, file_storage, get_doc_blocks_graph

__all__ = [
    "BoundingBox",
    "CanonicalBlock",
    "CanonicalChunk",
    "CanonicalDocument",
    "CanonicalOutlineNode",
    "CanonicalPage",
    "CanonicalTable",
    "CitationTarget",
    "FileStorage",
    "MinerUParser",
    "RawFilesStructureBuilder",
    "StructuredResult",
    "build_canonical_blocks",
    "build_canonical_chunks",
    "build_canonical_document",
    "build_canonical_outlines",
    "build_canonical_tables",
    "build_graph_from_rawfiles",
    "build_structured_from_rawfiles",
    "build_structured_index_for_doc",
    "build_table_representations",
    "classify_table",
    "extract_table_features",
    "file_storage",
    "get_doc_blocks_graph",
    "mineru_parser",
]


def __getattr__(name: str):
    if name == "build_vector_records":
        from docs_core.write.indexing.vector_indexer import build_vector_records
        return build_vector_records
    if name == "summarize_vector_records":
        from docs_core.write.indexing.vector_indexer import summarize_vector_records
        return summarize_vector_records
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
