"""Agent 工具契约与适配层（P2.1，§6.3）。

循环层不直接修改 engtools；通过 `AgentTool` 适配现有 BaseTool / 检索器 / 图谱。
"""
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from angineer_core.base_contracts import Evidence

logger = logging.getLogger(__name__)


@dataclass
class AgentTool:
    """循环层工具。"""

    name: str
    description: str  # 给模型看的中文描述
    parameters_schema: Dict[str, Any]  # JSON Schema，进 prompt / 校验
    handler: Callable[..., Dict[str, Any]]  # 实际执行体
    read_only: bool = False  # 检索类 True；权限与审计用
    execution_mode: str = "parallel"  # parallel | sequential
    timeout_s: int = 120  # 覆盖默认超时

    def to_schema_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters_schema,
        }


@dataclass
class ToolResult:
    """工具执行结果。"""

    call_id: str
    name: str
    content: str  # 喂回模型的文本（JSON 序列化）
    is_error: bool = False
    terminate: bool = False  # P3 举旗：整批全票才提前停
    raw: Dict[str, Any] = field(default_factory=dict)  # citations 等，进 meta 不进 content


def _default_schema() -> Dict[str, Any]:
    return {"type": "object", "properties": {}}


class EngtoolAdapter:
    """包装 engtools.ToolRegistry 中的 BaseTool。"""

    @staticmethod
    def from_registry(
        name: str,
        description: Optional[str] = None,
        parameters_schema: Optional[Dict[str, Any]] = None,
        *,
        config_name: Optional[str] = None,
        mode: Optional[str] = None,
        read_only: bool = False,
        execution_mode: str = "parallel",
        timeout_s: int = 120,
    ) -> AgentTool:
        def handler(**kwargs: Any) -> Dict[str, Any]:
            from engtools.BaseTool import ToolRegistry

            tool = ToolRegistry.get_tool(name)
            if tool is None:
                raise LookupError(f"Tool not found: {name}")
            run_kwargs = dict(kwargs)
            if config_name:
                run_kwargs["config_name"] = config_name
            if mode:
                run_kwargs["mode"] = mode
            result = tool.run(**run_kwargs)
            if result is None:
                result = {}
            if not isinstance(result, dict):
                result = {"result": result}
            return result

        return AgentTool(
            name=name,
            description=description or name,
            parameters_schema=parameters_schema or _default_schema(),
            handler=handler,
            read_only=read_only,
            execution_mode=execution_mode,
            timeout_s=timeout_s,
        )


def _serialize_model(value: Any) -> Dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {
            key: _serialize_value(getattr(value, key))
            for key in value.__dataclass_fields__
        }
    return dict(value or {})


def _serialize_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {key: _serialize_value(getattr(value, key)) for key in value.__dataclass_fields__}
    if isinstance(value, (list, tuple)):
        return [_serialize_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _serialize_value(val) for key, val in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


class MarkerAllocator:
    """run 级引用标记分配器：每个工具前缀全局递增。"""

    def __init__(self) -> None:
        self._counters: Dict[str, int] = {}

    def next(self, prefix: str) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}{n}"


def _assign_cites(items: list, allocator: MarkerAllocator, prefix: str) -> None:
    for item in items:
        metadata = getattr(item, "metadata", None)
        if metadata is not None:
            metadata["cite"] = allocator.next(prefix)


def _items_to_evidences(items: list, *, kind: str, source: str, library_id: str) -> List[Dict[str, Any]]:
    """RetrievedItem 列表 → Evidence 序列化 dict（统一证据模型；items 字段保留做展示兼容）。"""
    evidences: List[Dict[str, Any]] = []
    for item in items:
        metadata = getattr(item, "metadata", None) or {}
        evidence = Evidence(
            evidence_id=str(getattr(item, "item_id", "") or ""),
            kind=kind,
            doc_id=str(getattr(item, "doc_id", "") or ""),
            doc_title=str(metadata.get("doc_title") or getattr(item, "title", "") or ""),
            content=str(getattr(item, "text", "") or ""),
            page_idx=metadata.get("page_idx"),
            page_label=metadata.get("page_label"),
            section_path=str(metadata.get("section_path") or ""),
            score=float(getattr(item, "rerank_score", None) or getattr(item, "score", 0.0) or 0.0),
            source=source,
            library_id=library_id,
            metadata={
                "cite": metadata.get("cite"),
                "citation_target_id": getattr(item, "citation_target_id", None),
                "fusion_sources": metadata.get("fusion_sources") or [],
            },
        )
        evidences.append(evidence.model_dump(mode="json"))
    return evidences


def _entities_to_evidences(entities: list, *, library_id: str) -> List[Dict[str, Any]]:
    """图谱实体 → Evidence 序列化 dict（kind=graph_entity）。"""
    evidences: List[Dict[str, Any]] = []
    for entity in entities:
        data = _serialize_model(entity)
        evidence = Evidence(
            evidence_id=str(data.get("entity_id") or data.get("id") or data.get("name") or ""),
            kind="graph_entity",
            content=str(data.get("description") or data.get("name") or ""),
            source="graph",
            library_id=library_id,
            metadata=data,
        )
        evidences.append(evidence.model_dump(mode="json"))
    return evidences


def _run_knowledge_search(
    *,
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    doc_nodes: Optional[List[Any]] = None,
    top_k: int = 20,
    task_type: str = "content_qa",
    filters: Any = None,
    dense: Any = None,
    sparse: Any = None,
    clause: Any = None,
    prefix: str = "K",
    marker_allocator: Optional[MarkerAllocator] = None,
    rerank: bool = False,
    retrieval_client: Any = None,
) -> Dict[str, Any]:
    """执行知识库正文检索（dense/sparse/clause 融合），供 knowledge_search 与 entity_search 回退共用。

    3b：配置 ANGINEER_DOCS_API_URL（或显式注入 retrieval_client）时走 docs-api HTTP 检索，
    失败回退本地进程内检索；未配置时保持本地路径不变。
    """
    nodes = list(doc_nodes or [])
    doc_title_map = {
        str(getattr(node, "id", "") or ""): str(getattr(node, "title", "") or "")
        for node in nodes
    }
    if retrieval_client is None:
        from angineer_core.docs_retrieval_client import client_from_env

        retrieval_client = client_from_env()
    if retrieval_client is not None:
        try:
            items = retrieval_client.retrieve(
                mode="text",
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                top_k=top_k,
                task_type=task_type,
                filters=filters,
            )
            return _assemble_search_result(
                query=query, items=items, library_id=library_id,
                doc_title_map=doc_title_map, prefix=prefix,
                marker_allocator=marker_allocator, rerank=rerank, task_type=task_type,
                kind="text", source="knowledge_search",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("docs-api 检索失败，回退本地进程内检索: %s", exc)

    from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.step09_query.retrieval import fuse_candidates

    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        doc_ids=list(doc_ids or []),
        top_k=top_k,
        filters=filters,
    )
    dense_r = dense
    sparse_r = sparse
    clause_r = clause
    if dense_r is None or sparse_r is None or clause_r is None:
        from docs_core.step09_query.retrieval.clause_resolver import ClauseResolver
        from docs_core.step09_query.retrieval.dense_retriever import DenseRetriever
        from docs_core.step09_query.retrieval.sparse_retriever import SparseRetriever

        dense_r = dense_r or DenseRetriever()
        sparse_r = sparse_r or SparseRetriever()
        clause_r = clause_r or ClauseResolver()

    sources: Dict[str, List[Any]] = {}
    try:
        sources["dense"] = list(dense_r.retrieve(request, nodes, task_type) or [])
    except Exception as exc:  # noqa: BLE001
        sources["dense"] = []
        sources["dense_error"] = str(exc)
    try:
        sources["sparse"] = list(sparse_r.retrieve(request, nodes, task_type) or [])
    except Exception as exc:  # noqa: BLE001
        sources["sparse"] = []
        sources["sparse_error"] = str(exc)
    try:
        sources["clause"] = list(clause_r.retrieve(request, nodes, task_type) or [])
    except Exception as exc:  # noqa: BLE001
        sources["clause"] = []
        sources["clause_error"] = str(exc)

    candidate_sources = {k: v for k, v in sources.items() if isinstance(v, list)}
    if not candidate_sources:
        return {"error": "检索全部失败", "detail": {k: v for k, v in sources.items() if k.endswith("_error")}}
    items, _debug = fuse_candidates(candidate_sources, task_type=task_type, top_k=top_k)
    return _assemble_search_result(
        query=query, items=items, library_id=library_id,
        doc_title_map=doc_title_map, prefix=prefix,
        marker_allocator=marker_allocator, rerank=rerank, task_type=task_type,
        kind="text", source="knowledge_search",
    )


def _assemble_search_result(
    *,
    query: str,
    items: list,
    library_id: str,
    doc_title_map: Dict[str, str],
    prefix: str,
    marker_allocator: Optional[MarkerAllocator],
    rerank: bool,
    task_type: str,
    kind: str,
    source: str,
) -> Dict[str, Any]:
    """检索后装配：rerank → 引用标记 → doc_title 前缀 → items/evidences/citations。"""
    if rerank:
        from angineer_core.retrieval_pipeline import rerank_candidates

        items = rerank_candidates(query, items, task_type=task_type)
    _assign_cites(items, marker_allocator or MarkerAllocator(), prefix)
    for item in items:
        doc_title = doc_title_map.get(str(item.doc_id or ""), "") or str(item.metadata.get("doc_title") or "")
        if not doc_title:
            continue
        item.metadata["doc_title"] = doc_title
        text_prefix = f"《{doc_title}》"
        text = str(item.text or "")
        if text and text_prefix not in text:
            item.text = f"{text_prefix} {text}"
    result = {"items": [_serialize_model(item) for item in items], "total": len(items)}
    result["evidences"] = _items_to_evidences(items, kind=kind, source=source, library_id=library_id)
    citations = _build_relevant_citations(query, items)
    if citations:
        result["citations"] = citations
    return result


def _build_relevant_citations(query: str, items: list, limit: int = 5) -> List[Dict[str, Any]]:
    """从融合候选中挑选“真正有用”的引用：查询短语精确命中优先，无命中时按重排分取前 limit 条。"""
    if not items:
        return []
    from docs_core.step09_query.retrieval.query_normalizer import build_query_phrases, normalize_match_text

    query_phrases = build_query_phrases(query)
    selected: List[Any] = []
    if query_phrases:
        phrase_hits: List[Any] = []
        for item in items:
            compact = normalize_match_text(f"{item.title}\n{item.text}")
            if any(phrase in compact for phrase in query_phrases):
                phrase_hits.append(item)
        if phrase_hits:
            selected = phrase_hits[:limit]
    if not selected:
        selected = items[:limit]

    citations: List[Dict[str, Any]] = []
    for item in selected:
        doc_title = str(item.metadata.get("doc_title") or item.title or "")
        citations.append({
            "target_id": str(getattr(item, "citation_target_id", None) or item.item_id or ""),
            "doc_id": str(item.doc_id or ""),
            "doc_title": doc_title,
            "marker": str(item.metadata.get("cite") or ""),
            "page_idx": int(item.metadata.get("page_idx", 0) or 0),
            "page_label": item.metadata.get("page_label"),
            "section_path": str(item.metadata.get("section_path") or ""),
            "snippet": str(item.text or "")[:200],
            "score": float(item.rerank_score or item.score or 0.0),
            "fusion_sources": item.metadata.get("fusion_sources") or [],
        })
    return citations


class RetrieverAdapter:
    """包装 step09_query 五路检索器与图谱检索。"""

    @staticmethod
    def knowledge_search(
        *,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        task_type: str = "content_qa",
        filters: Any = None,
        dense: Any = None,
        sparse: Any = None,
        clause: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            return _run_knowledge_search(
                query=query,
                library_id=library_id,
                doc_ids=doc_ids,
                doc_nodes=doc_nodes,
                top_k=top_k,
                task_type=task_type,
                filters=filters,
                dense=dense,
                sparse=sparse,
                clause=clause,
                prefix="K",
                marker_allocator=marker_allocator,
                rerank=rerank,
                retrieval_client=retrieval_client,
            )

        return AgentTool(
            name="knowledge_search",
            description="在知识库正文中检索规范条文、概念、定义与条款，返回候选段落。概念/定义/“XX 是什么”类问题应优先使用本工具。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索问句"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )

    @staticmethod
    def table_search(
        *,
        library_id: str = "default",
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        filters: Any = None,
        table: Any = None,
        formula: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            client = retrieval_client
            if client is None:
                from angineer_core.docs_retrieval_client import client_from_env

                client = client_from_env()
            if client is not None:
                try:
                    items = client.retrieve(
                        mode="table",
                        query=query,
                        library_id=library_id,
                        doc_ids=doc_ids,
                        top_k=top_k,
                        filters=filters,
                    )
                    return _assemble_search_result(
                        query=query, items=items, library_id=library_id,
                        doc_title_map={}, prefix="T",
                        marker_allocator=marker_allocator, rerank=rerank, task_type="table_qa",
                        kind="table", source="table_search",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("docs-api 表格检索失败，回退本地进程内检索: %s", exc)

            from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
            from docs_core.step09_query.retrieval import fuse_candidates

            request = KnowledgeQueryRequest(
                query=query,
                library_id=library_id,
                doc_ids=list(doc_ids or []),
                top_k=top_k,
                filters=filters,
            )
            nodes = list(doc_nodes or [])
            table_r = table
            formula_r = formula
            if table_r is None or formula_r is None:
                from docs_core.step09_query.retrieval.formula_retriever import FormulaRetriever
                from docs_core.step09_query.retrieval.table_retriever import TableRetriever

                table_r = table_r or TableRetriever()
                formula_r = formula_r or FormulaRetriever()

            sources: Dict[str, List[Any]] = {}
            try:
                sources["table"] = list(table_r.retrieve(request, nodes) or [])
            except Exception as exc:  # noqa: BLE001
                sources["table"] = []
                sources["table_error"] = str(exc)
            try:
                sources["formula"] = list(formula_r.retrieve(request, nodes) or [])
            except Exception as exc:  # noqa: BLE001
                sources["formula"] = []
                sources["formula_error"] = str(exc)

            candidate_sources = {k: v for k, v in sources.items() if isinstance(v, list)}
            if not candidate_sources:
                return {"error": "表格检索全部失败", "detail": {k: v for k, v in sources.items() if k.endswith("_error")}}
            items, _debug = fuse_candidates(candidate_sources, task_type="table_qa", top_k=top_k)
            return _assemble_search_result(
                query=query, items=items, library_id=library_id,
                doc_title_map={}, prefix="T",
                marker_allocator=marker_allocator, rerank=rerank, task_type="table_qa",
                kind="table", source="table_search",
            )

        return AgentTool(
            name="table_search",
            description="在知识库中检索表格、公式与计算依据，返回候选条目。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "检索问句"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )

    @staticmethod
    def entity_search(
        *,
        library_id: str,
        db_path: Optional[str] = None,
        limit: int = 20,
        doc_ids: Optional[List[str]] = None,
        doc_nodes: Optional[List[Any]] = None,
        top_k: int = 20,
        task_type: str = "content_qa",
        filters: Any = None,
        marker_allocator: Optional[MarkerAllocator] = None,
        rerank: bool = False,
        retrieval_client: Any = None,
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            from docs_core.step07_graph.graph_store import GraphStore

            store = GraphStore(
                db_path or os.environ.get("KG_DB_PATH", os.path.join("data", "knowledge_graph.sqlite"))
            )
            # 图谱实体当前无 library_id 维度（graph_entities 表无 scope 列），检索为全库；
            # scope 随行返回供前端/evals 追踪，多库隔离待图谱 schema 演进。
            entities = store.search_entities(query, limit=limit)
            result: Dict[str, Any] = {
                "entities": [_serialize_model(entity) for entity in entities],
                "total": len(entities),
                "scope": {"library_id": library_id, "doc_ids": list(doc_ids or [])},
            }
            result["evidences"] = _entities_to_evidences(entities, library_id=library_id)
            if not entities:
                # 图谱无实体时自动回退正文检索，避免“是什么/定义”类问题被误判为无证据
                fallback = _run_knowledge_search(
                    query=query,
                    library_id=library_id,
                    doc_ids=doc_ids,
                    doc_nodes=doc_nodes,
                    top_k=top_k,
                    task_type=task_type,
                    filters=filters,
                    prefix="E",
                    marker_allocator=marker_allocator,
                    rerank=rerank,
                    retrieval_client=retrieval_client,
                )
                if fallback.get("error"):
                    result["fallback_error"] = fallback["error"]
                else:
                    result["items"] = fallback.get("items") or []
                    result["citations"] = fallback.get("citations") or []
                    result["evidences"] = result["evidences"] + (fallback.get("evidences") or [])
                    result["note"] = "知识图谱未找到匹配实体，已自动检索知识库正文，请基于 items 字段中的证据回答。"
            return result

        return AgentTool(
            name="entity_search",
            description="在知识图谱中检索实体及其关系，返回实体条目；仅适用于图谱实体关系类问题。若图谱无匹配，会自动回退检索知识库正文（items 字段）。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "实体关键词"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )


class SopRunnerAdapter:
    """SOP 执行工具（P4 接入）：IntentClassifier 路由 → SopRunner.run_sop → 步骤 trace。"""

    @staticmethod
    def sop_execute(
        *,
        timeout_s: int = 300,
        sops: Optional[List[Any]] = None,
        sop_loader: Any = None,
        classifier: Any = None,
        llm_client: Any = None,
        config_name: Optional[str] = None,
        mode: str = "instruct",
        runner: Any = None,
        memory: Any = None,
        step_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
    ) -> AgentTool:
        def handler(
            sop_query: Optional[str] = None,
            args: Optional[Dict[str, Any]] = None,
            **_kwargs: Any,
        ) -> Dict[str, Any]:
            from angineer_core.base_config import SOP_ROUTE_CONFIDENCE_THRESHOLD

            query = str(sop_query or "").strip()
            if not query:
                return {"error": "缺少 sop_query 参数"}

            if classifier is None:
                from angineer_core.classifier import IntentClassifier

                available = list(sops or [])
                if not available and sop_loader is not None:
                    available = list(sop_loader.load_all() or [])
                published = [
                    sop for sop in available if getattr(sop, "status", "published") == "published"
                ]
                if not published:
                    return {"error": "无可执行的已发布 SOP"}
                effective_classifier = IntentClassifier(published, llm_client=llm_client)
            else:
                effective_classifier = classifier

            route_result = effective_classifier.route(
                query, config_name=config_name, mode=mode
            )
            selected_sop = route_result.sop
            if selected_sop is None or route_result.confidence < SOP_ROUTE_CONFIDENCE_THRESHOLD:
                return {
                    "error": "未匹配到合适的 SOP",
                    "reason": route_result.reason or "SOP 路由未命中",
                    "confidence": route_result.confidence,
                }

            from angineer_core.sop_runner import SopRunner

            executor = runner
            if executor is None:
                executor = SopRunner(
                    config_name=config_name,
                    mode=mode,
                    memory=memory,
                    llm_client=llm_client,
                )

            initial_context = {"user_query": query}
            initial_context.update(route_result.args or {})
            if isinstance(args, dict):
                initial_context.update(args)

            final_context = executor.run_sop(
                selected_sop, initial_context, step_callback=step_callback
            )
            sop_trace = SopRunner._build_sop_trace(executor, selected_sop)
            citations = SopRunner._build_citations_from_sop_trace(executor)
            success_steps = sum(1 for s in sop_trace if s.get("status") == "success")
            failed_steps = sum(1 for s in sop_trace if s.get("status") not in ("success", "pending"))
            return {
                "sop_id": selected_sop.id,
                "sop_name": selected_sop.name_zh or selected_sop.name_en or selected_sop.id,
                "confidence": route_result.confidence,
                "summary": (
                    f"命中 SOP {selected_sop.id}，执行 {len(sop_trace)} 步，"
                    f"成功 {success_steps} 步，失败 {failed_steps} 步"
                ),
                "steps": [
                    {
                        "step_id": s.get("step_id"),
                        "step_name": s.get("step_name"),
                        "status": s.get("status"),
                        "outputs": s.get("outputs"),
                    }
                    for s in sop_trace
                ],
                "final_context": final_context or {},
                "sop_trace": sop_trace,
                "citations": citations,
                "route_reason": route_result.reason or "",
            }

        return AgentTool(
            name="sop_execute",
            description="执行一条标准作业程序（SOP），返回计算/查表结果与步骤轨迹。",
            parameters_schema={
                "type": "object",
                "properties": {
                    "sop_query": {"type": "string", "description": "要交给 SOP 路由的问题"},
                    "args": {"type": "object", "description": "SOP 所需参数"},
                },
                "required": ["sop_query"],
            },
            handler=handler,
            read_only=False,
            execution_mode="sequential",
            timeout_s=timeout_s,
        )


def result_to_content(value: Dict[str, Any]) -> str:
    """把 handler 返回的 dict 序列化为喂回模型的文本。"""
    return json.dumps(value, ensure_ascii=False, default=str)
