"""知识检索服务（3b）：五路召回 + 融合 + doc_title 注入。

边界：本模块只做召回与融合；rerank、引用标记分配、Evidence 装配由调用方负责。
供 docs-api 内部检索端点与（回退路径下）angineer-core 本地直调共用。
"""
import logging
from typing import Any, Dict, List, Optional

from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
from docs_core.step09_query.retrieval import fuse_candidates

logger = logging.getLogger(__name__)

_SOURCE_LABELS = {
    "text": ("dense", "sparse", "clause"),
    "table": ("table", "formula"),
}
_ERROR_MESSAGES = {
    "text": "检索全部失败",
    "table": "表格检索全部失败",
}


def _load_doc_nodes(library_id: str, doc_ids: Optional[List[str]]) -> list:
    """加载知识库 document 节点；失败时返回空列表（检索降级，不阻塞）。"""
    try:
        from docs_core.docs_service import get_docs_service

        kp = get_docs_service()
        nodes = [n for n in kp.list_nodes(library_id) if getattr(n, "type", "") == "document"]
        if doc_ids:
            ids = {str(doc_id) for doc_id in doc_ids if str(doc_id).strip()}
            nodes = [n for n in nodes if getattr(n, "id", "") in ids]
        return nodes
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载知识库节点失败，doc_title 注入跳过: %s", exc)
        return []


def _serialize_item(item: Any) -> Dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    if hasattr(item, "__dataclass_fields__"):
        return {key: getattr(item, key) for key in item.__dataclass_fields__}
    return dict(item or {})


def retrieve_knowledge(
    *,
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    top_k: int = 20,
    task_type: str = "content_qa",
    filters: Any = None,
    mode: str = "text",
    dense: Any = None,
    sparse: Any = None,
    clause: Any = None,
    table: Any = None,
    formula: Any = None,
    doc_nodes: Optional[List[Any]] = None,
) -> Dict[str, Any]:
    """按 mode 召回对应多路检索器并融合；metadata 注入 doc_title。"""
    if mode not in _SOURCE_LABELS:
        return {"error": f"未知检索模式: {mode}"}

    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        doc_ids=list(doc_ids or []),
        top_k=top_k,
        filters=filters,
    )
    nodes = list(doc_nodes) if doc_nodes is not None else _load_doc_nodes(library_id, doc_ids)

    if mode == "text":
        if dense is None or sparse is None or clause is None:
            from docs_core.step09_query.retrieval.clause_resolver import ClauseResolver
            from docs_core.step09_query.retrieval.dense_retriever import DenseRetriever
            from docs_core.step09_query.retrieval.sparse_retriever import SparseRetriever

            dense = dense or DenseRetriever()
            sparse = sparse or SparseRetriever()
            clause = clause or ClauseResolver()
        retrievers = {"dense": dense, "sparse": sparse, "clause": clause}
    else:
        if table is None or formula is None:
            from docs_core.step09_query.retrieval.formula_retriever import FormulaRetriever
            from docs_core.step09_query.retrieval.table_retriever import TableRetriever

            table = table or TableRetriever()
            formula = formula or FormulaRetriever()
        retrievers = {"table": table, "formula": formula}

    sources: Dict[str, List[Any]] = {}
    stage_times: Dict[str, float] = {}
    import time

    for name, retriever in retrievers.items():
        _t = time.perf_counter()
        try:
            if mode == "text":
                sources[name] = list(retriever.retrieve(request, nodes, task_type) or [])
            else:
                sources[name] = list(retriever.retrieve(request, nodes) or [])
        except Exception as exc:  # noqa: BLE001
            sources[name] = []
            sources[f"{name}_error"] = str(exc)
        stage_times[name] = time.perf_counter() - _t

    candidate_sources = {k: v for k, v in sources.items() if isinstance(v, list)}
    if not any(candidate_sources.values()) and any(k.endswith("_error") for k in sources):
        return {
            "error": _ERROR_MESSAGES[mode],
            "detail": {k: v for k, v in sources.items() if k.endswith("_error")},
        }

    fuse_task_type = task_type if mode == "text" else "table_qa"
    _t = time.perf_counter()
    items, debug = fuse_candidates(candidate_sources, task_type=fuse_task_type, top_k=top_k)
    stage_times["fuse"] = time.perf_counter() - _t
    logger.info(
        "retrieve_knowledge 分段计时: %s items=%d mode=%s query=%r",
        " ".join(f"{k}={v:.2f}s" for k, v in stage_times.items()),
        len(items),
        mode,
        query[:40],
    )

    doc_title_map = {
        str(getattr(node, "id", "") or ""): str(getattr(node, "title", "") or "")
        for node in nodes
    }
    for item in items:
        metadata = getattr(item, "metadata", None)
        if metadata is None:
            continue
        doc_title = doc_title_map.get(str(getattr(item, "doc_id", "") or ""), "")
        if doc_title:
            metadata["doc_title"] = doc_title

    return {
        "items": [_serialize_item(item) for item in items],
        "total": len(items),
        "debug": debug or {},
    }
