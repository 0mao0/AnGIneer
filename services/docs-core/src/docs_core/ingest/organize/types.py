"""Docs canonical schema 类型定义。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


BlockType = Literal[
    "title",
    "paragraph",
    "list_item",
    "table",
    "table_caption",
    "figure",
    "figure_caption",
    "header_footer",
    "footnote",
    "formula",
    "unknown",
]

ChunkType = Literal[
    "content",
    "outline_anchor",
    "list_procedure",
    "table_text_row",
    "table_mapping_row",
    "table_summary",
    "schema_desc",
]

TableType = Literal[
    "numeric_dense",
    "text_dense",
    "hybrid",
    "mapping_enum",
]


class BoundingBox(BaseModel):
    """统一的矩形框坐标。"""

    x0: float = 0.0
    y0: float = 0.0
    x1: float = 0.0
    y1: float = 0.0


class CanonicalPage(BaseModel):
    """文档页面。"""

    doc_id: str
    page_idx: int
    width: float = 0.0
    height: float = 0.0
    rotation: int = 0
    image_path: Optional[str] = None


class CanonicalBlock(BaseModel):
    """原子内容块。"""

    block_id: str
    doc_id: str
    page_idx: int = 0
    block_type: BlockType = "unknown"
    text: str = ""
    text_clean: str = ""
    bbox: Optional[BoundingBox] = None
    reading_order: int = 0
    title_level: Optional[int] = None
    section_path: str = ""
    source: str = "mineru"
    source_ref: Optional[str] = None
    parent_block_id: Optional[str] = None


class CanonicalOutlineNode(BaseModel):
    """章节树节点。"""

    outline_id: str
    doc_id: str
    level: int = 1
    title: str
    section_path: str = ""
    page_idx: int = 0
    anchor_block_id: Optional[str] = None
    parent_outline_id: Optional[str] = None


class CitationTarget(BaseModel):
    """统一引用目标。"""

    target_id: str
    target_type: str
    doc_id: str
    page_idx: int = 0
    bbox: Optional[BoundingBox] = None
    section_path: str = ""
    display_title: str = ""
    snippet: str = ""


class CanonicalChunk(BaseModel):
    """可检索内容片段。"""

    chunk_id: str
    doc_id: str
    chunk_type: ChunkType = "content"
    text: str = ""
    text_clean: str = ""
    token_count: int = 0
    section_path: str = ""
    page_start: int = 0
    page_end: int = 0
    source_block_ids: List[str] = Field(default_factory=list)
    citation_targets: List[CitationTarget] = Field(default_factory=list)
    version: str = "0.1.0"


class CanonicalTable(BaseModel):
    """统一表格对象。"""

    table_id: str
    doc_id: str
    page_start: int = 0
    page_end: int = 0
    title: str = ""
    caption: str = ""
    bbox: Optional[BoundingBox] = None
    table_type: TableType = "hybrid"
    header_rows: List[List[str]] = Field(default_factory=list)
    body_rows: List[List[str]] = Field(default_factory=list)
    units: List[str] = Field(default_factory=list)
    row_count: int = 0
    col_count: int = 0
    source_block_ids: List[str] = Field(default_factory=list)
    summary: str = ""
    row_keys: List[str] = Field(default_factory=list)
    text_chunks: List[str] = Field(default_factory=list)
    version: str = "0.1.0"


class CanonicalDocument(BaseModel):
    """规范化文档对象。"""

    doc_id: str
    library_id: str
    title: str
    source_file_name: str = ""
    source_file_type: str = "pdf"
    schema_version: str = "1.0.0"
    parse_version: str = "0.1.0"
    language: str = "zh"
    page_count: int = 0
    status: str = "pending"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    pages: List[CanonicalPage] = Field(default_factory=list)
    blocks: List[CanonicalBlock] = Field(default_factory=list)
    outlines: List[CanonicalOutlineNode] = Field(default_factory=list)
    chunks: List[CanonicalChunk] = Field(default_factory=list)
    tables: List[CanonicalTable] = Field(default_factory=list)
