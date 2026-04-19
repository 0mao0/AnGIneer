"""知识查询协议模型。"""
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


TaskType = Literal[
    "content_qa",
    "definition_qa",
    "locate_qa",
    "table_qa",
    "schema_qa",
    "analytic_sql",
    "mixed",
]


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
    doc_ids: List[str] = Field(default_factory=list)
    session_id: Optional[str] = None
    history: List[Dict[str, Any]] = Field(default_factory=list)
    mode: str = "auto"
    top_k: int = 5
    include_debug: bool = False
    include_retrieved: bool = False
    filters: Optional[KnowledgeQueryFilter] = None


class KnowledgeCitation(BaseModel):
    """知识引用项。"""

    target_id: str
    target_type: str
    doc_id: str
    doc_title: str
    page_idx: int = 0
    section_path: str = ""
    snippet: str = ""
    score: float = 0.0


class RetrievedItem(BaseModel):
    """检索命中项。"""

    item_id: str
    entity_type: str
    doc_id: str
    title: str = ""
    text: str = ""
    score: float = 0.0
    rerank_score: Optional[float] = None
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
