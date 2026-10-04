"""知识查询协议模型。"""
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from docs_core.models.types import (
    SCHEMA_VERSION,
    STRUCTURED_DOC_GRAPH_STRATEGY,
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
)


TaskType = Literal[
    "content_qa",
    "definition_qa",
    "locate_qa",
    "table_qa",
    "schema_qa",
    "analytic_sql",
    "mixed",
]


class KnowledgeNode(BaseModel):
    """知识库节点（query/ingest/write 共享的树模型契约）。"""

    id: str
    title: str
    type: str
    parent_id: Optional[str] = None
    visible: bool = False
    library_id: str
    file_path: Optional[str] = None
    status: str = "pending"
    parse_progress: int = 0
    parse_stage: Optional[str] = None
    parse_error: Optional[str] = None
    parse_task_id: Optional[str] = None
    strategy: str = STRUCTURED_DOC_GRAPH_STRATEGY
    schema_version: str = SCHEMA_VERSION
    sort_order: int = 0
    deleted: bool = False
    created_at: datetime = datetime.now()
    updated_at: datetime = datetime.now()


class KnowledgeQueryFilter(BaseModel):
    """知识查询过滤条件。"""

    section_path: Optional[str] = None
    page_start: Optional[int] = None
    page_end: Optional[int] = None
    tags: List[str] = Field(default_factory=list)


class KnowledgeQueryRequest(BaseModel):
    """知识查询请求。"""

    query: str
    library_id: str = "default"
    # 多库勾选（阶段三 D8）：空列表=单库（library_id），非空=集合且 library_id=集合首项
    library_ids: List[str] = Field(default_factory=list)
    doc_ids: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    mode: str = "auto"
    top_k: int = 5
    include_debug: bool = False
    include_retrieved: bool = False
    filters: Optional[KnowledgeQueryFilter] = None


def normalize_library_ids(
    library_ids: Optional[List[str]] = None,
    library_id: str = "",
) -> List[str]:
    """归一化知识库集合：去重（保持顺序）、去空白项；空集回退 [library_id or "default"]。

    多库问答（阶段三）的唯一归一化点：docs-api / aichat-api / retrieve_service 共用，
    各层不得各自再去重排序（顺序=主库语义，首项即兼容单值）。
    """
    seen: List[str] = []
    for raw in library_ids or []:
        lib = str(raw or "").strip()
        if lib and lib not in seen:
            seen.append(lib)
    if not seen:
        seen = [str(library_id or "").strip() or "default"]
    return seen


class CitationRichMedia(BaseModel):
    """引用项富媒体信息。"""

    table_html: str = ""
    math_content: str = ""
    image_path: str = ""
    image_paths: List[str] = Field(default_factory=list)
    rich_media_order: List[Dict[str, Any]] = Field(default_factory=list)
    source_file_name: str = ""


class KnowledgeCitation(BaseModel):
    """知识引用项。"""

    target_id: str
    target_type: str
    doc_id: str
    doc_title: str
    page_idx: int = 0
    section_path: str = ""
    snippet: str = ""
    content: str = ""
    content_type: str = "text"
    score: float = 0.0
    rich_media: Optional[CitationRichMedia] = None


class RetrievedItem(BaseModel):
    """检索命中项。"""

    item_id: str
    entity_type: str
    doc_id: str
    title: str = ""
    text: str = ""
    score: float = 0.0
    rerank_score: Optional[float] = None
    citation_target_id: Optional[str] = None
    retrieval_policy: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SqlPayload(BaseModel):
    """结构化查询结果。"""

    generated_sql: str = ""
    execution_status: str = "not_run"
    result_preview: Any = None
    linked_schema: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""


class KnowledgeQueryResponse(BaseModel):
    """知识查询响应。"""

    query_id: str
    task_type: TaskType
    strategy: str
    answer: str
    citations: List[KnowledgeCitation] = Field(default_factory=list)
    retrieved_items: List[RetrievedItem] = Field(default_factory=list)
    sql: Optional[SqlPayload] = None
    confidence: float = 0.0
    latency_ms: int = 0
    debug: Dict[str, Any] = Field(default_factory=dict)


class SemanticRetrievalRequest(BaseModel):
    """docs-core 语义检索请求，供 angineer-core 调度时使用。"""

    query: str
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    top_k: int = 5
    filters: Optional[KnowledgeQueryFilter] = None


class SemanticRetrievalResponse(BaseModel):
    """docs-core 语义检索响应。"""

    items: List[RetrievedItem] = Field(default_factory=list)
    citations: List[KnowledgeCitation] = Field(default_factory=list)
    latency_ms: int = 0


class SqlRetrievalRequest(BaseModel):
    """docs-core SQL 检索请求，供 angineer-core 调度时使用。"""

    query: str
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    sql_filters: Dict[str, Any] = Field(default_factory=dict)


class SqlRetrievalResponse(BaseModel):
    """docs-core SQL 检索响应。"""

    sql_payload: Optional[SqlPayload] = None
    items: List[RetrievedItem] = Field(default_factory=list)
    citations: List[KnowledgeCitation] = Field(default_factory=list)
    fallback_used: bool = False
    latency_ms: int = 0
