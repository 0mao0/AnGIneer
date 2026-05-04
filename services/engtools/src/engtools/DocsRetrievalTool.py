"""docs-core 检索工具，封装语义检索和 SQL 检索为 ToolRegistry 可调用工具。"""
from typing import Any, Dict, List, Optional

from .BaseTool import BaseTool, register_tool


def _resolve_doc_nodes(library_id: str, doc_ids: Optional[List[str]] = None) -> list:
    """解析文档节点列表。"""
    from docs_core.knowledge_service import KnowledgeNode, knowledge_service

    library_nodes = knowledge_service.list_nodes(library_id)
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
        from docs_core.query_protocols.contracts import (
            KnowledgeQueryRequest,
            SemanticRetrievalResponse,
        )
        from docs_core.retrieval.dense_retriever import dense_retriever
        from docs_core.retrieval.sparse_retriever import sparse_retriever
        from docs_core.retrieval.hybrid_retriever import fuse_candidates

        doc_nodes = _resolve_doc_nodes(library_id, doc_ids)
        kq_request = KnowledgeQueryRequest(
            query=query,
            library_id=library_id,
            doc_ids=doc_ids or [],
            top_k=top_k,
        )
        dense_hits = dense_retriever.retrieve(kq_request, doc_nodes, "content_qa")
        sparse_hits = sparse_retriever.retrieve(kq_request, doc_nodes, "content_qa")
        fused = fuse_candidates(dense_hits, sparse_hits, top_k=top_k)

        return {
            "items": [item.model_dump(mode="json") for item in fused],
            "citations": [],
            "latency_ms": 0,
        }


@register_tool
class DocsSqlTool(BaseTool):
    """docs-core SQL 检索工具。"""
    name = "docs_sql"
    description_en = "SQL retrieval tool: search for structured data using text-to-SQL. Inputs: query (str), library_id (str), doc_ids (list, optional), sql_filters (dict, optional)"
    description_zh = "SQL 检索工具：使用 text-to-SQL 查询结构化数据。输入参数：query (str), library_id (str), doc_ids (list, 可选), sql_filters (dict, 可选)"

    def run(self, query: str = "", library_id: str = "default", doc_ids: Optional[List[str]] = None, sql_filters: Optional[Dict[str, Any]] = None, **kwargs) -> Dict[str, Any]:
        """执行 SQL 检索，返回命中的知识片段列表。"""
        from docs_core.query_protocols.contracts import (
            KnowledgeQueryRequest,
            RetrievedItem,
            SqlRetrievalResponse,
        )
        from docs_core.text2sql.schema_linker import link_schema
        from docs_core.text2sql.sql_validator import validate_sql
        from docs_core.text2sql.sql_executor import execute_sql

        doc_nodes = _resolve_doc_nodes(library_id, doc_ids)
        kq_request = KnowledgeQueryRequest(
            query=query,
            library_id=library_id,
            doc_ids=doc_ids or [],
        )
        schema_result = link_schema(query, kq_request, doc_nodes)
        if not schema_result.get("supported"):
            return {"items": [], "fallback_used": True}

        table_name = schema_result.get("table_name", "")
        if not table_name:
            return {"items": [], "fallback_used": True}

        sql = f"SELECT * FROM {table_name} WHERE doc_id IN ({','.join(['?' for _ in doc_nodes])})"
        params: List[Any] = [node.id for node in doc_nodes]

        business_filters = schema_result.get("business_filters", {})
        sql_filters = sql_filters or {}
        merged_filters = {**business_filters, **sql_filters}

        if "clause_id" in merged_filters:
            sql += " AND clause_id = ?"
            params.append(merged_filters["clause_id"])

        is_valid, reason = validate_sql(sql)
        if not is_valid:
            return {"items": [], "fallback_used": True}

        try:
            sql_result = execute_sql(sql, params)
            items = []
            if sql_result and isinstance(sql_result, list):
                for row in sql_result:
                    item_id = row.get("chunk_id") or row.get("block_id") or ""
                    items.append({
                        "item_id": item_id,
                        "entity_type": row.get("chunk_type") or row.get("block_type") or "",
                        "doc_id": row.get("doc_id") or "",
                        "title": row.get("section_path") or "",
                        "text": row.get("text_clean") or row.get("text") or "",
                        "score": 1.0,
                        "metadata": row,
                    })
            return {"items": items, "fallback_used": False}
        except Exception:
            return {"items": [], "fallback_used": True}
