"""docs-api 内部检索端点（3b）：薄封装 docs_core retrieve_service，供 angineer-core 远程调用。

scope（library_id/doc_ids）随行透传；rerank 与装配由调用方负责。
错误以 {"error": ...} 载荷返回（工具语义），调用方据此回退本地路径。

端点清单：
- POST /internal/retrieve       五路召回融合检索
- POST /internal/entity-search  图谱实体检索（供 agent_tools entity_search 走 HTTP）
- GET  /internal/doc-nodes      文档节点清单（供 policy_query/agent 加载 scope 走 HTTP）
- POST /internal/graph-append-note  图谱实体描述追加标记（供 dream_cycle 孤儿实体收编走 HTTP）
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field

from docs_core.step09_query.retrieve_service import retrieve_knowledge

logger = logging.getLogger(__name__)

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


class EntitySearchInternalRequest(BaseModel):
    query: str
    library_id: str = "default"
    limit: int = 20


def _serialize_entity(entity: Any) -> Dict[str, Any]:
    """GraphEntity dataclass → 可 JSON 序列化 dict（枚举取 value）。"""
    return {
        "entity_id": entity.entity_id,
        "name": entity.name,
        "layer": entity.layer.value,
        "aliases": list(entity.aliases or []),
        "description": entity.description or "",
        "source_doc": entity.source_doc or "",
        "source_clause": entity.source_clause or "",
        "library_id": entity.library_id,
        "status": entity.status.value,
        "proposed_doc_id": entity.proposed_doc_id or "",
        "proposed_by": entity.proposed_by or "",
        "reject_reason": entity.reject_reason or "",
        "reviewed_at": entity.reviewed_at or "",
        "reviewed_by": entity.reviewed_by or "",
        "created_at": entity.created_at or "",
        "updated_at": entity.updated_at or "",
    }


@retrieve_router.post("/internal/entity-search")
def entity_search_internal(request: EntitySearchInternalRequest) -> Dict[str, Any]:
    from docs_core.paths import resolve_graph_db_path
    from docs_core.step07_graph.graph_store import GraphStore

    store = GraphStore(str(resolve_graph_db_path()))
    entities = store.search_entities(
        request.query, limit=request.limit, library_id=request.library_id
    )
    return {
        "entities": [_serialize_entity(entity) for entity in entities],
        "total": len(entities),
    }


@retrieve_router.get("/internal/doc-nodes")
def list_doc_nodes_internal(library_id: str = "default") -> Dict[str, Any]:
    """返回指定库的 document 节点清单（KnowledgeNode 契约字段）。"""
    from docs_core.docs_service import get_docs_service

    kp = get_docs_service()
    nodes = [
        node
        for node in kp.list_nodes(library_id)
        if getattr(node, "type", "") == "document"
    ]
    return {
        "nodes": [
            node.model_dump(mode="json") if hasattr(node, "model_dump") else dict(node)
            for node in nodes
        ],
        "total": len(nodes),
    }


class GraphAppendNoteRequest(BaseModel):
    entity_id: str
    marker: str


@retrieve_router.post("/internal/graph-append-note")
def graph_append_note_internal(request: GraphAppendNoteRequest) -> Dict[str, Any]:
    """向图谱实体 description 追加标记（dream_cycle 孤儿实体人工保留/删除的收编入口）。"""
    from docs_core.paths import resolve_graph_db_path
    from docs_core.step07_graph.graph_store import GraphStore

    marker = str(request.marker or "").strip()
    if not marker:
        return {"error": "marker 不能为空"}
    store = GraphStore(str(resolve_graph_db_path()))
    entity = store.get_entity(request.entity_id)
    if entity is None:
        return {"error": f"实体不存在: {request.entity_id}"}
    entity.description = (entity.description or "") + " " + marker
    store.upsert_entity(entity)
    return {"status": "ok", "entity_id": request.entity_id}
