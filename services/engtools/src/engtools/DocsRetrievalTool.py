"""docs-core 检索工具，封装语义检索为 ToolRegistry 可调用工具。"""
from typing import Any, Dict, List, Optional

from .BaseTool import BaseTool, register_tool


def _resolve_doc_nodes(library_id: str, doc_ids: Optional[List[str]] = None) -> list:
    """解析文档节点列表。"""
    from docs_core.docs_service import KnowledgeNode, docs_service

    library_nodes = docs_service.list_nodes(library_id)
    doc_nodes = [node for node in library_nodes if node.type == "document"]
    if doc_ids:
        requested = set(doc_ids)
        doc_nodes = [node for node in doc_nodes if node.id in requested]
    return doc_nodes


@register_tool
class DocsRetrievalTool(BaseTool):
    """docs-core 语义检索工具。"""
    name = "docs_retrieval"
    description_en = "Semantic retrieval tool: search for relevant knowledge fragments using dense+sparse hybrid retrieval. Inputs: query (str), library_id (str), doc_ids (list, optional), top_k (int)"
    description_zh = "语义检索工具：使用稠密+稀疏混合检索查找相关知识片段。输入参数：query (str), library_id (str), doc_ids (list, 可选), top_k (int)"

    def run(self, query: str = "", library_id: str = "default", doc_ids: Optional[List[str]] = None, top_k: int = 5, **kwargs) -> Dict[str, Any]:
        """执行语义检索，返回命中的知识片段列表。"""
        from docs_core.step09_query.protocols.contracts import (
            KnowledgeQueryRequest,
            SemanticRetrievalResponse,
        )
        from docs_core.step09_query.retrieval.dense_retriever import dense_retriever
        from docs_core.step09_query.retrieval.sparse_retriever import sparse_retriever
        from docs_core.step09_query.retrieval.hybrid_retriever import fuse_candidates

        doc_nodes = _resolve_doc_nodes(library_id, doc_ids)
        kq_request = KnowledgeQueryRequest(
            query=query,
            library_id=library_id,
            doc_ids=doc_ids or [],
            top_k=top_k,
        )
        dense_hits = dense_retriever.retrieve(kq_request, doc_nodes, "content_qa")
        sparse_hits = sparse_retriever.retrieve(kq_request, doc_nodes, "content_qa")
        fused, _fuse_debug = fuse_candidates(
            {"dense": dense_hits, "sparse": sparse_hits},
            task_type="content_qa",
            top_k=top_k,
        )

        return {
            "items": [item.model_dump(mode="json") for item in fused],
            "citations": [],
            "latency_ms": 0,
        }

