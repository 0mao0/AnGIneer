"""docs-api 内部检索端点（3b）：薄封装 docs_core retrieve_service，供 angineer-core 远程调用。

scope（library_id/doc_ids）随行透传；rerank 与装配由调用方负责。
错误以 {"error": ...} 载荷返回（工具语义），调用方据此回退本地路径。
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from docs_core.step09_query.retrieve_service import retrieve_knowledge

retrieve_router = APIRouter()


class RetrieveInternalRequest(BaseModel):
    query: str
    library_id: str = "default"
    doc_ids: List[str] = Field(default_factory=list)
    top_k: int = 20
    task_type: str = "content_qa"
    filters: Optional[Dict[str, Any]] = None
    mode: str = "text"


@retrieve_router.post("/internal/retrieve")
def retrieve_internal(request: RetrieveInternalRequest) -> Dict[str, Any]:
    return retrieve_knowledge(
        query=request.query,
        library_id=request.library_id,
        doc_ids=request.doc_ids,
        top_k=request.top_k,
        task_type=request.task_type,
        filters=request.filters,
        mode=request.mode,
    )
