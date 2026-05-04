"""知识查询服务统一入口。"""
import time
import uuid
from typing import Dict, List

from docs_core.answering.answer_assembler import assemble_answer
from docs_core.answering.citation_builder import build_citations
from docs_core.executors import ContentExecutor, FormulaExecutor, SqlExecutor, TableExecutor, summarize_candidates
from docs_core.knowledge_service import KnowledgeNode, KnowledgeService, knowledge_service
from docs_core.query.contracts import KnowledgeQueryRequest, KnowledgeQueryResponse
from docs_core.query.execution_planner import build_execution_plan
from docs_core.query.intent_parser import parse_intent


class KnowledgeQueryService:
    """统一知识查询入口服务。"""

    def __init__(self, knowledge_service_impl: KnowledgeService | None = None) -> None:
        self._default_strategy = "canonical_hybrid_v1"
        self._knowledge_service = knowledge_service_impl or knowledge_service
        content_executor = ContentExecutor()
        self._executors = {
            "content": content_executor,
            "table": TableExecutor(content_executor=content_executor),
            "formula": FormulaExecutor(content_executor=content_executor),
            "sql": SqlExecutor(knowledge_service_impl=self._knowledge_service),
        }

    # 解析本次查询涉及的文档节点。
    def _resolve_document_nodes(self, request: KnowledgeQueryRequest) -> List[KnowledgeNode]:
        library_nodes = self._knowledge_service.list_nodes(request.library_id)
        doc_nodes = [node for node in library_nodes if node.type == "document"]
        if request.doc_ids:
            requested = set(request.doc_ids)
            doc_nodes = [node for node in doc_nodes if node.id in requested]
        return doc_nodes

    # 执行知识查询并返回统一响应。
    def query(self, request: KnowledgeQueryRequest) -> KnowledgeQueryResponse:
        started_at = time.time()
        task_type = parse_intent(request.query, request.mode)
        execution_plan = build_execution_plan(request.query, task_type)
        doc_nodes = self._resolve_document_nodes(request)
        doc_title_map: Dict[str, str] = {node.id: node.title for node in doc_nodes}
        executor = self._executors[execution_plan.executor_name]
        execution_result = executor.execute(request, doc_nodes, task_type)
        candidate_summary = summarize_candidates(execution_result.candidates)
        sql_payload = execution_result.sql_payload
        if sql_payload is not None:
            citations = []
            answer = execution_result.answer
            confidence = execution_result.confidence
        else:
            citations = build_citations(execution_result.candidates, doc_title_map, knowledge_service=self._knowledge_service)
            answer, confidence = assemble_answer(request.query, task_type, citations, execution_result.candidates)
        latency_ms = int((time.time() - started_at) * 1000)

        return KnowledgeQueryResponse(
            query_id=f"q-{uuid.uuid4().hex[:12]}",
            task_type=task_type,
            strategy=execution_plan.strategy or self._default_strategy,
            answer=answer,
            citations=citations,
            retrieved_items=execution_result.candidates if request.include_retrieved else [],
            sql=sql_payload,
            confidence=confidence,
            latency_ms=latency_ms,
            debug={
                "route": task_type,
                "executor": execution_plan.executor_name,
                "retrieval_route": execution_result.retrieval_route,
                "fallback_used": execution_result.fallback_used,
                "doc_count": len(doc_nodes),
                "dense_hits": len(execution_result.dense_candidates),
                "sparse_hits": len(execution_result.sparse_candidates),
                "evidence_sufficient": execution_result.evidence_sufficient,
                "pre_filter_returned_hits": len(execution_result.pre_filter_candidates),
                "returned_hits": len(execution_result.candidates),
                "fusion_debug": execution_result.fusion_debug,
                "candidate_summary": candidate_summary,
                **execution_result.extra_debug,
            } if request.include_debug else {},
        )


knowledge_query_service = KnowledgeQueryService()

__all__ = [
    "KnowledgeQueryService",
    "knowledge_query_service",
]
