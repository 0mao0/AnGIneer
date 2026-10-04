"""知识检索服务（3b）：五路召回 + 融合 + doc_title 注入。

边界：本模块只做召回与融合；rerank、引用标记分配、Evidence 装配由调用方负责。
供 docs-api 内部检索端点与（回退路径下）angineer-core 本地直调共用。
"""
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional

from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest, normalize_library_ids
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


def _resolve_retrievers(
    mode: str,
    dense: Any = None,
    sparse: Any = None,
    clause: Any = None,
    table: Any = None,
    formula: Any = None,
) -> "tuple[tuple[str, Any], ...]":
    """按 mode 返回 (name, retriever) 有序对；缺位懒建默认实例（单库/多库共用，顺序即 stage_times 键序）。"""
    if mode == "text":
        if dense is None or sparse is None or clause is None:
            from docs_core.step09_query.retrieval.clause_resolver import ClauseResolver
            from docs_core.step09_query.retrieval.dense_retriever import DenseRetriever
            from docs_core.step09_query.retrieval.sparse_retriever import SparseRetriever

            dense = dense or DenseRetriever()
            sparse = sparse or SparseRetriever()
            clause = clause or ClauseResolver()
        return (("dense", dense), ("sparse", sparse), ("clause", clause))
    if table is None or formula is None:
        from docs_core.step09_query.retrieval.formula_retriever import FormulaRetriever
        from docs_core.step09_query.retrieval.table_retriever import TableRetriever

        table = table or TableRetriever()
        formula = formula or FormulaRetriever()
    return (("table", table), ("formula", formula))


def _inject_doc_titles(items: List[Any], nodes: List[Any]) -> None:
    """按节点表把 doc_title 注入候选 metadata（单库=本路 nodes，多库=并集，规则同一条）。"""
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


def _assemble_result(
    items: List[Any],
    *,
    debug: Dict[str, Any],
    stage_times: Dict[str, float],
    partial_errors: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """组装响应（键序 items/total/debug/stage_times[/partial_errors][/warning]，单库多库共用）。"""
    result: Dict[str, Any] = {
        "items": [_serialize_item(item) for item in items],
        "total": len(items),
        "debug": debug or {},
        # 分段计时随响应上浮（方案 E，req-table-retrieval-latency §10）：docs-api 路由透传，
        # 引擎侧（agent_tools）选择性消费落 ops jsonl；docs-core 不感知观测设施。
        "stage_times": dict(stage_times),
    }
    if partial_errors:
        result["partial_errors"] = partial_errors
    # 向量库健康守卫：维度不匹配时给用户可见提示（守卫模块不可用时不影响检索）
    try:
        from docs_core.startup_guard import get_retrieve_warning
        warning = get_retrieve_warning()
        if warning:
            result["warning"] = warning
    except Exception:
        pass
    return result


def retrieve_knowledge(
    *,
    query: str,
    library_id: str = "default",
    library_ids: Optional[List[str]] = None,
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

    library_ids = normalize_library_ids(library_ids, library_id)
    library_id = library_ids[0]
    if len(library_ids) > 1:
        return _retrieve_multi(
            query=query, library_ids=library_ids, doc_ids=doc_ids, top_k=top_k,
            task_type=task_type, filters=filters, mode=mode,
            dense=dense, sparse=sparse, clause=clause, table=table, formula=formula,
            doc_nodes=doc_nodes,
        )

    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        library_ids=library_ids,
        doc_ids=list(doc_ids or []),
        top_k=top_k,
        filters=filters,
    )
    nodes = list(doc_nodes) if doc_nodes is not None else _load_doc_nodes(library_id, doc_ids)

    retrievers = _resolve_retrievers(
        mode, dense=dense, sparse=sparse, clause=clause, table=table, formula=formula,
    )

    sources: Dict[str, List[Any]] = {}
    stage_times: Dict[str, float] = {}
    import time

    for name, retriever in retrievers:
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

    _inject_doc_titles(items, nodes)

    return _assemble_result(items, debug=debug, stage_times=stage_times)


# 多库合并候选池（D9）：单库 top_k 保持调用方值，多库固定 40，
# RRF 只做粗排、裁决权留给引擎侧 rerank + top 15 截断。
_MULTI_FUSED_TOP_K = 40
# (组, 路) 全组合并行的线程上限（评审 Minor：裸 9 具名化）。
_MULTI_MAX_WORKERS = 9


def _resolve_collection(library_id: str) -> str:
    """库 → 向量 collection（组）路由键；注册表不可用时回退按库各自成组。"""
    try:
        from docs_core.library_registry import resolve_collection  # 实名已核验：library_registry.py:261

        return str(resolve_collection(library_id) or library_id)
    except Exception:  # noqa: BLE001
        return library_id


def _retrieve_multi(
    *,
    query: str,
    library_ids: List[str],
    doc_ids: Optional[List[str]],
    top_k: int,
    task_type: str,
    filters: Any,
    mode: str,
    dense: Any,
    sparse: Any,
    clause: Any,
    table: Any,
    formula: Any,
    doc_nodes: Optional[List[Any]],
) -> Dict[str, Any]:
    """多库扇出：按 collection 分组并行检索，按 (source, library) 分池 RRF 融合。"""
    # 1) 每库加载 document 节点 + doc→lib 映射
    nodes_by_lib: Dict[str, List[Any]] = {lib: [] for lib in library_ids}
    doc_lib_map: Dict[str, str] = {}
    if doc_nodes is not None:
        # 外部注入节点（@ 提及/评测组合用法）：按注册表读穿归属分桶——
        # 直接平铺会让第一个库认领全部节点、来源库全标错（评审 P2-12）
        try:
            from docs_core.docs_service import get_docs_service

            _svc = get_docs_service()
        except Exception:  # noqa: BLE001 — 服务不可用时全部节点按首库归属
            _svc = None

        def _lib_of(node: Any) -> str:
            doc_id = str(getattr(node, "id", "") or "")
            if _svc is not None:
                try:
                    lib = str(_svc.meta_store.get_node_library_id(doc_id) or "")
                except Exception:  # noqa: BLE001 — meta 库读失败只降级该节点按首库归属，不拖垮整请求
                    lib = ""
                if lib:
                    return lib
            return library_ids[0]
        for node in doc_nodes:
            lib = _lib_of(node)
            bucket = nodes_by_lib.setdefault(lib if lib in nodes_by_lib else library_ids[0], [])
            bucket.append(node)
    else:
        for lib in library_ids:
            nodes_by_lib[lib] = _load_doc_nodes(lib, doc_ids)
    for lib, lib_nodes in nodes_by_lib.items():
        for node in lib_nodes:
            doc_lib_map[str(getattr(node, "id", "") or "")] = lib

    # 2) 按 collection 分组（同组共享向量桶与 canonical 组文件，一次调用覆盖）
    libs_by_collection: Dict[str, List[str]] = {}
    for lib in library_ids:
        libs_by_collection.setdefault(_resolve_collection(lib), []).append(lib)

    # 3) 检索器实例（与单库路径同款懒加载，共用 _resolve_retrievers）
    retriever_kinds = _resolve_retrievers(
        mode, dense=dense, sparse=sparse, clause=clause, table=table, formula=formula,
    )

    # 4) (组, 路) 全组合并行执行；组内请求 library_id=组首库（collection 路由）、
    #    library_ids=组内集合（sparse FTS 求交前移）、doc_nodes=组内并集。
    # 线程安全注记（评审 P2-13）：Dense/Sparse/Clause/Table/Formula 实例跨线程共享，
    # 单库路径原无并发——实现时确认各 retriever 及其 port 无可变实例状态
    # （检索期只读 + 局部变量），失败已由 partial_errors 兜底。
    def _run_one(group_libs: List[str], kind: str, retriever: Any):
        group_nodes = [n for lib in group_libs for n in nodes_by_lib.get(lib, [])]
        try:
            request = KnowledgeQueryRequest(
                query=query,
                library_id=group_libs[0],
                library_ids=list(group_libs),
                doc_ids=list(doc_ids or []),
                top_k=top_k,
                filters=filters,
            )
            if mode == "text":
                items = list(retriever.retrieve(request, group_nodes, task_type) or [])
            else:
                items = list(retriever.retrieve(request, group_nodes) or [])
            return kind, group_libs, items, None
        except Exception as exc:  # noqa: BLE001 — 单路失败按 partial_errors 兜底，但必须留痕
            logger.warning(
                "retrieve_knowledge(multi) %s@%s 失败: %s",
                kind, "+".join(group_libs), exc, exc_info=True,
            )
            return kind, group_libs, [], str(exc)

    import time

    stage_times: Dict[str, float] = {}
    _t = time.perf_counter()
    jobs = [
        (group_libs, kind, retriever)
        for group_libs in libs_by_collection.values()
        for kind, retriever in retriever_kinds
    ]
    results = []
    with ThreadPoolExecutor(max_workers=min(_MULTI_MAX_WORKERS, max(1, len(jobs)))) as pool:
        for res in pool.map(lambda j: _run_one(*j), jobs):
            results.append(res)
    stage_times["retrieve_fanout"] = time.perf_counter() - _t

    # 5) 打库标签 + 按 (source, library) 分池
    candidate_sources: Dict[str, List[Any]] = {}
    errors: Dict[str, str] = {}
    for kind, group_libs, items, error in results:
        if error:
            errors[f"{kind}@{'+'.join(group_libs)}"] = error
        for item in items:
            doc_id = str(getattr(item, "doc_id", "") or "")
            lib = doc_lib_map.get(doc_id) or group_libs[0]
            metadata = getattr(item, "metadata", None)
            if metadata is not None:
                metadata["library_id"] = lib
            pool_key = f"{kind}@{lib}"
            candidate_sources.setdefault(pool_key, []).append(item)

    if not any(candidate_sources.values()) and errors:
        return {"error": _ERROR_MESSAGES[mode], "detail": errors}

    # 6) 融合（池键带 @lib，权重按基名；D9 固定 40 候选池，pool_cap=None 放开 20 硬顶）
    fuse_task_type = task_type if mode == "text" else "table_qa"
    _t = time.perf_counter()
    items, debug = fuse_candidates(candidate_sources, task_type=fuse_task_type, top_k=_MULTI_FUSED_TOP_K, pool_cap=None)
    stage_times["fuse"] = time.perf_counter() - _t
    logger.info(
        "retrieve_knowledge(multi) 分段计时: %s items=%d mode=%s libs=%s query=%r",
        " ".join(f"{k}={v:.2f}s" for k, v in stage_times.items()),
        len(items), mode, ",".join(library_ids), query[:40],
    )

    # 7) doc_title 注入（与单库同规则；nodes 并集）
    all_nodes = [n for lib in library_ids for n in nodes_by_lib.get(lib, [])]
    _inject_doc_titles(items, all_nodes)

    return _assemble_result(items, debug=debug, stage_times=stage_times, partial_errors=errors or None)
