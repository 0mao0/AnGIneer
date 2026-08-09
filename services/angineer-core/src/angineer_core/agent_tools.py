"""Agent 工具契约与适配层（P2.1，§6.3）。

循环层不直接修改 engtools；通过 `AgentTool` 适配现有 BaseTool / 检索器 / 图谱。
"""
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


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
        rerank: bool = False,
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
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
            if rerank:
                from angineer_core.retrieval_pipeline import rerank_candidates

                items = rerank_candidates(query, items, task_type=task_type)
            return {
                "items": [_serialize_model(item) for item in items],
                "total": len(items),
            }

        return AgentTool(
            name="knowledge_search",
            description="在知识库中检索规范条文、概念与条款，返回候选段落。",
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
        rerank: bool = False,
    ) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
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
            if rerank:
                from angineer_core.retrieval_pipeline import rerank_candidates

                items = rerank_candidates(query, items, task_type="table_qa")
            return {
                "items": [_serialize_model(item) for item in items],
                "total": len(items),
            }

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
    def entity_search(*, db_path: Optional[str] = None, limit: int = 20) -> AgentTool:
        def handler(query: Optional[str] = None, **_kwargs: Any) -> Dict[str, Any]:
            if not query:
                return {"error": "缺少 query 参数"}
            from docs_core.step07_graph.graph_store import GraphStore

            store = GraphStore(
                db_path or os.environ.get("KG_DB_PATH", os.path.join("data", "knowledge_graph.sqlite"))
            )
            entities = store.search_entities(query, limit=limit)
            return {"entities": [_serialize_model(entity) for entity in entities], "total": len(entities)}

        return AgentTool(
            name="entity_search",
            description="在知识图谱中检索实体及其关系，返回实体条目。",
            parameters_schema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "实体关键词"}},
                "required": ["query"],
            },
            handler=handler,
            read_only=True,
        )


class SopRunnerAdapter:
    """SOP 执行工具（P4 接入）：IntentClassifier 路由 → Dispatcher.run_sop → 步骤 trace。"""

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
        dispatcher: Any = None,
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

            from angineer_core.dispatcher import Dispatcher

            executor = dispatcher
            if executor is None:
                executor = Dispatcher(
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
            sop_trace = Dispatcher._build_sop_trace(executor, selected_sop)
            citations = Dispatcher._build_citations_from_sop_trace(executor)
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
