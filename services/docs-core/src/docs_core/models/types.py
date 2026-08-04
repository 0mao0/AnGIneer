"""Docs canonical schema 类型定义。"""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# 表格四分类：canonical 数据模型自带字段取值，ingest 阶段产出、query 阶段消费。
TABLE_TYPE_NUMERIC_DENSE = "numeric_dense"
TABLE_TYPE_TEXT_DENSE = "text_dense"
TABLE_TYPE_HYBRID = "hybrid"
TABLE_TYPE_MAPPING_ENUM = "mapping_enum"

# 结构化知识库存储契约常量（KnowledgeNode/索引行共用）。
STRUCTURED_DOC_GRAPH_STRATEGY = "doc_blocks_graph_v1"
SCHEMA_VERSION = "1.0.0"


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
    "formula_block",
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
    printed_page_label: Optional[str] = None


class CanonicalBlock(BaseModel):
    """原子内容块。"""

    schema_version: str = "v2"
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
    inherited_chapter: Optional[str] = None
    entity_tags: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    exam_tags: List[str] = Field(default_factory=list)
    clause_id: Optional[str] = None
    contd_target_id: Optional[str] = None
    image_assoc_id: Optional[str] = None
    table_merge_id: Optional[str] = None
    raw_type: Optional[str] = None
    # 构建期旁路字段（阶段一）：原始表格 HTML 只进 table_html，text 保持 textified，避免污染 FTS。
    # 不落库 canonical_blocks 列式表；随 graph jsonl 节点与 doc_blocks 行保留。
    table_html: Optional[str] = None
    # 构建期旁路字段（阶段一）：公式语义契约（FormulaSemanticsContract），挂载点由阶段三统一投影时定。
    formula_semantics: Optional[dict] = None


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
    printed_page_label: Optional[str] = None

    @property
    def display_page_label(self) -> str:
        """展示页码：印刷页码优先，缺省回退物理页序（1-based）。"""
        return self.printed_page_label or str(self.page_idx + 1)


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
    inherited_chapter: Optional[str] = None
    entity_tags: List[str] = Field(default_factory=list)
    conditions: List[str] = Field(default_factory=list)
    exam_tags: List[str] = Field(default_factory=list)
    clause_id: Optional[str] = None
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
    citation_targets: List[CitationTarget] = Field(default_factory=list)
