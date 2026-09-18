"""agent_tools 检索/图谱配方适配器（C1 Seam 4，2026-09-19）。

从 angineer_core.agent_tools 平移进来的本地召回配方本体，逻辑零改动
（import 改包内相对路径、日志logger名随模块）。引擎经 angineer_core.ports
注册表消费本模块函数；本模块零 import angineer_core，只依赖 docs-core 自身实现。
"""
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_TABLE_QUERY_HINTS = (
    "查表", "取值", "参数表", "数据表", "尺度", "吨级", "载重吨",
    "设计船型", "总长", "型宽", "型深", "满载吃水", "DWT", "dwt",
)


def _looks_like_table_query(query: str) -> bool:
    """判断问题是否偏向查表取值（需要表格行数值）。"""
    text = str(query or "")
    return any(hint in text for hint in _TABLE_QUERY_HINTS)


def normalize_query(query: str) -> str:
    """中文数字条款号转阿拉伯数字（"第六十条"→"第60条"），提升 ClauseResolver 精确命中率。"""
    from .retrieval.query_normalizer import normalize_chinese_clause_numbers

    return normalize_chinese_clause_numbers(query)


def knowledge_local_search(
    *,
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    top_k: int = 20,
    task_type: str = "content_qa",
    filters: Any = None,
    nodes: Optional[List[Any]] = None,
    dense: Any = None,
    sparse: Any = None,
    clause: Any = None,
    formula: Any = None,
) -> Dict[str, Any]:
    """知识库本地召回配方：dense/sparse/clause 三路 + 条件 formula/table 路 + fuse + 表格文本兜底。

    返回 {"items": [...]}（已 fuse+兜底，未做 per-doc 去重截断——那一步在引擎装配层）
    或 {"error": "检索全部失败", "detail": {...}}。平移自 angineer_core.agent_tools
    ._run_knowledge_search 本地分支，逻辑零改动。
    """
    from .protocols.contracts import KnowledgeQueryRequest
    from .retrieval import fuse_candidates

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
        from .retrieval.clause_resolver import ClauseResolver
        from .retrieval.dense_retriever import DenseRetriever
        from .retrieval.sparse_retriever import SparseRetriever

        dense_r = dense_r or DenseRetriever()
        sparse_r = sparse_r or SparseRetriever()
        clause_r = clause_r or ClauseResolver()

    sources: Dict[str, List[Any]] = {}
    stage_times: Dict[str, float] = {}
    for _name, _retriever in (("dense", dense_r), ("sparse", sparse_r), ("clause", clause_r)):
        _t = time.perf_counter()
        try:
            sources[_name] = list(_retriever.retrieve(request, nodes, task_type) or [])
        except Exception as exc:  # noqa: BLE001
            sources[_name] = []
            sources[f"{_name}_error"] = str(exc)
        stage_times[_name] = time.perf_counter() - _t
    # 检索器异常此前被静默吞掉（只塞进 *_error），日志里与「确实没结果」完全同形，
    # 排查时只能靠两侧日志对拍。留痕（2026-09-11）。
    for _key, _err in list(sources.items()):
        if _key.endswith("_error"):
            logger.warning("knowledge_search %s 检索器异常，已按空结果继续: %s", _key, _err)
    from .retrieval.formula_retriever import FormulaRetriever, is_formula_query

    if is_formula_query(request.query, task_type):
        _t = time.perf_counter()
        try:
            formula_r = formula
            if formula_r is None:
                formula_r = FormulaRetriever()
            sources["formula"] = list(formula_r.retrieve(request, nodes) or [])
        except Exception as exc:  # noqa: BLE001
            sources["formula"] = []
            sources["formula_error"] = str(exc)
        stage_times["formula"] = time.perf_counter() - _t

    # 查表/数值/尺度类问题：把表格行数据一并并入正文检索，避免"搜到表标题却拿不到行数值"。
    table_items: List[Any] = []
    if (
        str(task_type).startswith("table_")
        or str(task_type) in {"locate_table", "locate_qa"}
        or _looks_like_table_query(request.query)
    ):
        _t = time.perf_counter()
        try:
            from .retrieval.table_retriever import TableRetriever

            table_r = TableRetriever()
            table_items = list(table_r.retrieve(request, nodes) or [])
            sources["table"] = table_items
        except Exception as exc:  # noqa: BLE001
            sources["table"] = []
            sources["table_error"] = str(exc)
        stage_times["table"] = time.perf_counter() - _t

    candidate_sources = {k: v for k, v in sources.items() if isinstance(v, list)}
    if not candidate_sources:
        return {"error": "检索全部失败", "detail": {k: v for k, v in sources.items() if k.endswith("_error")}}
    _t = time.perf_counter()
    items, _debug = fuse_candidates(candidate_sources, task_type=task_type, top_k=top_k)
    stage_times["fuse"] = time.perf_counter() - _t
    logger.info(
        "knowledge_search 分段计时(本地召回): %s items=%d query=%r",
        " ".join(f"{k}={v:.2f}s" for k, v in stage_times.items()),
        len(items),
        query[:40],
    )
    # 表格兜底：同一 table_id 的候选若只带了摘要（无行数值），用完整表格文本补全
    if table_items:
        table_text_by_id: Dict[str, str] = {}
        for item in table_items:
            tid = str((item.metadata or {}).get("table_id") or "")
            if tid:
                table_text_by_id.setdefault(tid, str(item.text or ""))
        for item in items:
            tid = str((item.metadata or {}).get("table_id") or "")
            full = table_text_by_id.get(tid) or ""
            if full and len(full) > len(str(item.text or "")):
                item.text = full
    return {"items": items}


def table_local_search(
    *,
    query: str,
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
    top_k: int = 20,
    filters: Any = None,
    nodes: Optional[List[Any]] = None,
    table: Any = None,
    formula: Any = None,
) -> Dict[str, Any]:
    """表格/公式本地召回配方。返回 {"items": [...]} 或
    {"error": "表格检索全部失败", "detail": {...}}。平移自 RetrieverAdapter.table_search
    本地分支，逻辑零改动。"""
    from .protocols.contracts import KnowledgeQueryRequest
    from .retrieval import fuse_candidates

    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        doc_ids=list(doc_ids or []),
        top_k=top_k,
        filters=filters,
    )
    table_r = table
    formula_r = formula
    if table_r is None or formula_r is None:
        from .retrieval.formula_retriever import FormulaRetriever
        from .retrieval.table_retriever import TableRetriever

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
    return {"items": items}


def entity_local_search(
    *,
    query: str,
    library_id: str,
    db_path: Optional[str] = None,
    limit: int = 20,
) -> List[Any]:
    """图谱本地直查（GraphStore 分支）。db_path 缺省按仓库根解析
    （容器里 cwd 是 services/aichat-api，不能用 cwd 相对）。平移自
    RetrieverAdapter.entity_search 本地分支，逻辑零改动。"""
    from ..paths import resolve_graph_db_path
    from ..step07_graph.graph_store import GraphStore

    graph_db = db_path or str(resolve_graph_db_path())
    store = GraphStore(db_path=graph_db)
    return store.search_entities(query, limit=limit, library_id=library_id)


def local_stats(library_id: Optional[str] = None) -> Dict[str, Any]:
    """进程内直查 SQLite 的统计聚合（HTTP 未配置/失败时的兜底）。

    口径与 docs-api GET /api/knowledge/stats 一致：文档以 nodes 表为准（deleted=0 排除软删），
    上传/存储以 parse_records 为准（status<>'deleted'）。平移自
    angineer_core.agent_tools._local_knowledge_stats，逻辑零改动。
    """
    import sqlite3
    from datetime import datetime, timedelta, timezone

    from ..paths import resolve_knowledge_meta_db_path, resolve_repo_root

    lib_clause = " AND library_id = ?" if library_id else ""
    lib_params: tuple = (library_id,) if library_id else ()
    now = datetime.now(timezone.utc)

    conn = sqlite3.connect(f"file:{resolve_knowledge_meta_db_path()}?mode=ro", uri=True)
    try:
        total = conn.execute(
            f"SELECT COUNT(*) FROM nodes WHERE deleted=0{lib_clause}", lib_params
        ).fetchone()[0]
        deleted = conn.execute(
            f"SELECT COUNT(*) FROM nodes WHERE deleted=1{lib_clause}", lib_params
        ).fetchone()[0]
        by_status = {
            r[0]: r[1]
            for r in conn.execute(
                f"SELECT status, COUNT(*) FROM nodes WHERE deleted=0{lib_clause} GROUP BY status",
                lib_params,
            )
        }
        by_library = [
            {"library_id": r[0], "library_name": r[1] or r[0], "count": r[2]}
            for r in conn.execute(
                "SELECT n.library_id, l.name, COUNT(*) FROM nodes n"
                " LEFT JOIN libraries l ON n.library_id = l.id"
                f" WHERE n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}"
                " GROUP BY n.library_id ORDER BY COUNT(*) DESC",
                lib_params,
            )
        ]
        pages_row = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(s.page_count),0), COALESCE(AVG(s.page_count),0)"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}",
            lib_params,
        ).fetchone()
        max_page_row = conn.execute(
            "SELECT n.id, n.title, s.page_count"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0{lib_clause.replace('library_id', 'n.library_id')}"
            " ORDER BY s.page_count DESC LIMIT 1",
            lib_params,
        ).fetchone()
        min_page_row = conn.execute(
            "SELECT n.id, n.title, s.page_count"
            " FROM doc_parse_stages s JOIN nodes n ON s.doc_id = n.id"
            f" WHERE s.stage='raw_parse' AND n.deleted=0 AND s.page_count > 0{lib_clause.replace('library_id', 'n.library_id')}"
            " ORDER BY s.page_count ASC LIMIT 1",
            lib_params,
        ).fetchone()
        # 标题清单：供 meta_query 通道回答"有哪些文章/规范"类列举型元数据问题
        # （与 docs-api GET /api/knowledge/stats 的 documents.titles 口径保持一致）
        title_rows = conn.execute(
            f"SELECT title, status FROM nodes WHERE deleted=0{lib_clause} ORDER BY title LIMIT 101",
            lib_params,
        ).fetchall()
    finally:
        conn.close()

    records_db = resolve_repo_root() / "data" / "parse_records.sqlite"
    rconn = sqlite3.connect(f"file:{records_db}?mode=ro", uri=True)
    try:
        rec_base = "status<>'deleted'" + lib_clause
        recent_7d = rconn.execute(
            f"SELECT COUNT(*) FROM parse_records WHERE {rec_base} AND created_at >= ?",
            lib_params + ((now - timedelta(days=7)).isoformat(),),
        ).fetchone()[0]
        recent_30d = rconn.execute(
            f"SELECT COUNT(*) FROM parse_records WHERE {rec_base} AND created_at >= ?",
            lib_params + ((now - timedelta(days=30)).isoformat(),),
        ).fetchone()[0]
        by_month = [
            {"month": r[0], "count": r[1]}
            for r in rconn.execute(
                f"SELECT substr(created_at,1,7), COUNT(*) FROM parse_records WHERE {rec_base}"
                " GROUP BY substr(created_at,1,7) ORDER BY 1",
                lib_params,
            )
        ]
        by_format = [
            {"format": (r[0] or "unknown").lstrip(".").lower() or "unknown", "count": r[1]}
            for r in rconn.execute(
                f"SELECT file_format, COUNT(*) FROM parse_records WHERE {rec_base} GROUP BY file_format ORDER BY 2 DESC",
                lib_params,
            )
        ]
        size_row = rconn.execute(
            f"SELECT COALESCE(SUM(file_size),0) FROM parse_records WHERE {rec_base}", lib_params
        ).fetchone()
    finally:
        rconn.close()

    return {
        "library_id": library_id,
        "generated_at": now.isoformat(),
        "documents": {
            "total": total,
            "deleted": deleted,
            "by_status": by_status,
            "by_library": by_library,
            "titles_total": total,
            "titles_truncated": len(title_rows) > 100,
            "titles": [{"title": r[0], "status": r[1]} for r in title_rows[:100]],
        },
        "uploads": {
            "recent_7d": recent_7d,
            "recent_30d": recent_30d,
            "by_month": by_month,
            "by_format": by_format,
        },
        "pages": {
            "docs_with_pages": pages_row[0],
            "total": pages_row[1],
            "avg_per_doc": round(pages_row[2], 1) if pages_row[2] else 0,
            "max": (
                {"doc_id": max_page_row[0], "title": max_page_row[1], "pages": max_page_row[2]}
                if max_page_row
                else None
            ),
            "min": (
                {"doc_id": min_page_row[0], "title": min_page_row[1], "pages": min_page_row[2]}
                if min_page_row
                else None
            ),
        },
        "storage": {"total_file_size_mb": round(size_row[0] / 1024 / 1024, 1)},
    }


def relevant_citations(query: str, items: list, limit: int = 5) -> List[Dict[str, Any]]:
    """从融合候选中挑选"真正有用"的引用：查询短语精确命中优先，无命中时按重排分取前 limit 条。

    平移自 angineer_core.agent_tools._build_relevant_citations，逻辑零改动。
    """
    if not items:
        return []
    from .retrieval.query_normalizer import build_query_phrases, normalize_match_text

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


def engtool_registry() -> Any:
    """返回 engtools ToolRegistry（惰性 import 在此，引擎不再认识 engtools 包）。"""
    from engtools.BaseTool import ToolRegistry

    return ToolRegistry