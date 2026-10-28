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


# 公开别名：请求级预热（aichat-api/route_pre）用它做「必输局不下注」的先验门
# ——表题的真实调用走 table_search（无检索 memo），预热产物结构性无法被消费
# （req-table-retrieval-latency §11）。
looks_like_table_query = _looks_like_table_query


def normalize_query(query: str) -> str:
    """中文数字条款号转阿拉伯数字（"第六十条"→"第60条"），提升 ClauseResolver 精确命中率。"""
    from .retrieval.query_normalizer import normalize_chinese_clause_numbers

    return normalize_chinese_clause_numbers(query)


def _tag_item_libraries(items: List[Any], nodes: Optional[List[Any]]) -> int:
    """逐条回填 item.metadata["library_id"]（多库集合下条目的库归属）。

    引擎侧按这份库标回填引用与证据的库归属：前端点引用用 citation.library_id 取文档，
    缺标时只能回退会话首库——非首库的文档必 404「Document not found」
    （2026-10-16 本地 6 库会话实踩：PDF 在 std-water、回退 std-highway）。
    HTTP 多库通道（retrieve_service._retrieve_multi）早有同样的打标，本地进程内通道此前没有。

    归属只取节点/meta 库的事实，取不到就不标：宁可不标（前端回退，与修复前同行为），
    也不按首库猜——误标会同时把 evidence.library_id 写错。
    """
    mapping: Dict[str, str] = {}
    unresolved: List[str] = []
    for node in nodes or []:
        doc_id = str(getattr(node, "id", "") or "").strip()
        if not doc_id:
            continue
        lib = str(getattr(node, "library_id", "") or "").strip()
        if lib:
            mapping[doc_id] = lib
        else:
            unresolved.append(doc_id)
    if unresolved:
        # 外部注入/旧装配的节点可能不带库标：按 meta 库读穿一次（同 _retrieve_multi 的归属分桶）
        try:
            from docs_core.docs_service import get_docs_service

            meta_store = get_docs_service().meta_store
        except Exception:  # noqa: BLE001 — 服务不可用只是不标，不拖垮检索
            meta_store = None
        if meta_store is not None:
            for doc_id in unresolved:
                try:
                    lib = str(meta_store.get_node_library_id(doc_id) or "").strip()
                except Exception:  # noqa: BLE001 — 单条读失败只跳过该条
                    lib = ""
                if lib:
                    mapping[doc_id] = lib
    tagged = 0
    for item in items:
        if isinstance(item, dict):
            metadata = item.get("metadata")
            doc_id = str(item.get("doc_id") or "")
        else:
            metadata = getattr(item, "metadata", None)
            doc_id = str(getattr(item, "doc_id", "") or "")
        if not isinstance(metadata, dict):
            continue
        lib = mapping.get(doc_id)
        if lib:
            metadata["library_id"] = lib
            tagged += 1
    return tagged


def knowledge_local_search(
    *,
    query: str,
    library_id: str = "default",
    library_ids: Optional[List[str]] = None,
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

    library_ids（阶段三 A7）：多库勾选集合透传——空=单库（library_id），非空=集合且
    library_id 归一为首项。集合语义分路生效：稀疏路按勾选集合做 SQL 过滤求交；
    稠密/条款/表格/公式路按集合首库路由 collection（降级路径暂无跨组扇出）。
    """
    from .protocols.contracts import KnowledgeQueryRequest, normalize_library_ids
    from .retrieval import fuse_candidates

    library_ids = normalize_library_ids(library_ids, library_id)
    library_id = library_ids[0]
    request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        library_ids=library_ids,
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
    # 多库集合逐条回填库标：引用/证据按库定位的真相源（缺标即前端回退会话首库 → 非首库 404）
    _tag_item_libraries(items, nodes)
    # stage_times 随返回值上浮：引擎层（agent_tools）选择性消费后落 ops jsonl，
    # docs-core 不感知观测设施（req-table-retrieval-latency §10 方案 E）。
    return {"items": items, "stage_times": dict(stage_times)}


def _merge_header_rows(header: List[Any]) -> List[str]:
    """多行表头压成一行：每列非空单元格按顺序拼接。

    财务表常见两行表头（「Fiscal Year / Fiscal Year / Fiscal Year」+「2019 / 2018 / 2017」），
    原样输出会得到三列同名「Fiscal Year」，模型无法把数值对到年份列；压成
    「Fiscal Year 2019 | Fiscal Year 2018 | Fiscal Year 2017」后列义唯一。
    """
    cols: List[str] = []
    for row in header:
        cells = row if isinstance(row, (list, tuple)) else [row]
        for i, cell in enumerate(cells):
            text = str(cell).strip()
            if not text:
                continue
            while len(cols) <= i:
                cols.append("")
            cols[i] = f"{cols[i]} {text}".strip()
    return [c or "（行标签）" for c in cols]


def _table_block_text(block: Dict[str, Any]) -> str:
    """表格块 → 可进证据的文本：表题 + 单行合并表头 + 每行数据独占一行。

    列序固定为表头顺序；数据行不再与表头拼行（2026-10-21 复核：早期"表头并进首行"
    是打印时替换换行造成的错觉，实际渲染本就是逐行；这里只修「多行表头列义重复」）。
    """
    rows = block.get("rows") or []
    header = block.get("header_rows") or []
    ctx = str(block.get("context") or "").strip()
    head = (f"表格《{ctx}》包含 {len(rows)} 行" if ctx else f"表格包含 {len(rows)} 行")
    lines = [head]
    merged = _merge_header_rows(header)
    if merged:
        lines.append("列：" + " | ".join(merged))
    for idx, row in enumerate(rows, 1):
        cells = row if isinstance(row, (list, tuple)) else [row]
        lines.append(f"{idx}. " + " | ".join(str(c).strip() for c in cells))
    return "\n".join(lines)


def _query_tokens(query: str) -> List[str]:
    """检索词：全量去重（不截前 20 个）——财务题的公式行项常出现在题干尾部，
    截断会丢掉 inventory/receivable/payable 这些唯一能与表头对上的词。"""
    import re

    seen, out = set(), []
    for tok in re.split(r"[^0-9a-zA-Z\u4e00-\u9fff]+", (query or "").lower()):
        if len(tok) < 3 or tok in seen:
            continue
        seen.add(tok)
        out.append(tok)
        if len(out) >= 40:
            break
    return out


def _doc_scoped_table_blocks(
    items: List[Any], *, query: str, library_id: str,
    doc_ids: Optional[List[str]], top_k: int,
) -> List[Any]:
    """doc 范围明确、但候选里没有「带行」的表时，直接按该文档 canonical 表格块补候选。

    2026-10-21 实踩：financebench 财务比率题原文（CCC/DIO/DSO/DPO）与利润表表头零词面
    交集，table_search 把 32 行利润表排到 12 条之外，模型只拿到 chunk 摘要、没有行数值，
    只能拒答。表本身在索引里（换 query "Cost of sales" 即命中），这里按 doc 范围兜底：
    词面命中的表优先，其余按原文顺序补足。兜底失败不影响主检索。
    """
    if not doc_ids or any(str(getattr(it, "entity_type", "") or "") == "table" for it in items):
        return items
    try:
        blocks = table_blocks_provider(library_id=library_id, doc_ids=list(doc_ids))
    except Exception as exc:  # noqa: BLE001
        logger.warning("doc 范围表格兜底失败: %s", exc)
        return items
    if not blocks:
        return items
    tokens = _query_tokens(query)
    scored = []
    for idx, block in enumerate(blocks):
        text = _table_block_text(block)
        score = sum(1 for t in tokens if t in text.lower())
        scored.append((score, idx, text, block))
    scored.sort(key=lambda x: (-x[0], x[1]))
    from .protocols.contracts import RetrievedItem

    extra = []
    for score, idx, text, block in scored[: max(1, min(int(top_k or 20), 8))]:
        extra.append(RetrievedItem(
            item_id=f"table-block-{block.get('doc_id', '')}-{block.get('page_idx', idx)}-{idx}",
            entity_type="table",
            doc_id=str(block.get("doc_id") or ""),
            title=str(block.get("context") or "")[:120],
            text=text,
            score=float(score),
            retrieval_policy="doc_table_fallback",
            metadata={"page_idx": block.get("page_idx"), "fallback": "doc_table"},
        ))
    if extra:
        logger.info("table_search doc 范围兜底：补 %d 张表（doc_ids=%s）", len(extra), doc_ids)
    return list(items) + extra


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

    # 分段计时（2026-09-26 表格检索提速观测报告 §9.4）：L2 查表题主路径此前完全无检索打点，
    # 只有 rerank 计时可见；对齐 knowledge_local_search 的分段计时口径，供前后对照。
    stage_times: Dict[str, float] = {}
    sources: Dict[str, List[Any]] = {}
    _t = time.perf_counter()
    try:
        sources["table"] = list(table_r.retrieve(request, nodes) or [])
    except Exception as exc:  # noqa: BLE001
        sources["table"] = []
        sources["table_error"] = str(exc)
    stage_times["table"] = time.perf_counter() - _t
    if "table_error" in sources:
        logger.warning("table_search %s 检索器异常，已按空结果继续: %s", "table", sources["table_error"])
    _t = time.perf_counter()
    try:
        sources["formula"] = list(formula_r.retrieve(request, nodes) or [])
    except Exception as exc:  # noqa: BLE001
        sources["formula"] = []
        sources["formula_error"] = str(exc)
    stage_times["formula"] = time.perf_counter() - _t
    if "formula_error" in sources:
        logger.warning("table_search %s 检索器异常，已按空结果继续: %s", "formula", sources["formula_error"])

    candidate_sources = {k: v for k, v in sources.items() if isinstance(v, list)}
    if not candidate_sources:
        return {"error": "表格检索全部失败", "detail": {k: v for k, v in sources.items() if k.endswith("_error")}}
    _t = time.perf_counter()
    items, _debug = fuse_candidates(candidate_sources, task_type="table_qa", top_k=top_k)
    items = _doc_scoped_table_blocks(
        items, query=query, library_id=library_id, doc_ids=doc_ids, top_k=top_k)
    stage_times["fuse"] = time.perf_counter() - _t
    logger.info(
        "table_search 分段计时(本地召回): %s items=%d query=%r",
        " ".join(f"{k}={v:.2f}s" for k, v in stage_times.items()),
        len(items),
        query[:40],
    )
    # 逐条回填库标（同 knowledge_local_search：表格条目的引用/证据也要能按库定位）
    _tag_item_libraries(items, nodes)
    # stage_times 随返回值上浮（同 knowledge_local_search，方案 E）
    return {"items": items, "stage_times": dict(stage_times)}


def entity_local_search(
    *,
    query: str,
    library_id: str,
    db_path: Optional[str] = None,
    limit: int = 20,
) -> List[Any]:
    """图谱本地直查（GraphStore 分支）。db_path 缺省按 **library_id 的库文件**解析
    （plan-graph-per-library-split；迁移期自动回退全局文件）。"""
    from ..step07_graph.graph_files import resolve_graph_db_for_library
    from ..step07_graph.graph_store import GraphStore

    graph_db = db_path or str(resolve_graph_db_for_library(library_id))
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
        # 标题清单：供 knowledge_stats 工具回答"有哪些文章/规范"类列举型元数据问题
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

    matters: Dict[str, Any] = {"catalog": False, "total": 0, "matters": []}
    if library_id:
        try:
            from .doc_search import list_matters

            matters = list_matters(library_id)
        except Exception:  # noqa: BLE001
            pass

    return {
        "library_id": library_id,
        "generated_at": now.isoformat(),
        "matters": matters,
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


def relevant_citations(query: str, items: list, limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """从融合候选中挑选引用：短语精确命中优先。

    limit=None/<=0 返回**全部** items——引用解析表必须覆盖所有 cite 标记，
    否则答案引用第 6 条以后的证据时前端无法解析、回退显示 doc_id（2026-10-22 实踩）。
    limit>0 保持旧语义（只取命中项/前 limit 条，供展示型调用）。
    """
    if not items:
        return []
    from .retrieval.query_normalizer import build_query_phrases, normalize_match_text

    cap = len(items) if limit is None or int(limit) <= 0 else min(int(limit), len(items))
    query_phrases = build_query_phrases(query)
    selected: List[Any] = []
    if query_phrases:
        phrase_hits: List[Any] = []
        for item in items:
            compact = normalize_match_text(f"{item.title}\n{item.text}")
            if any(phrase in compact for phrase in query_phrases):
                phrase_hits.append(item)
        if phrase_hits:
            if limit is None or int(limit) <= 0:
                hit_ids = {id(item) for item in phrase_hits}
                selected = phrase_hits + [item for item in items if id(item) not in hit_ids]
                selected = selected[:cap]
            else:
                selected = phrase_hits[:cap]
    if not selected:
        selected = items[:cap]

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


def table_blocks_provider(
    library_id: str = "default",
    doc_ids: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """canonical 表格块批量取数：供引擎 canonical_table_lookup 精确查表。

    返回 [{"doc_id", "header_rows", "rows", "context", "page_idx"}]；context 取
    CanonicalTable 已解析的 title/caption（等价老工具从 HTML 周边抠的表格上下文）。
    doc_ids 为空时取库内全部文档节点（与老工具全库找文件的语义对齐，调用方
    应尽量传 scope）。
    """
    from ..docs_service import docs_service

    # 按库解析组存储（多库修复 2026-10-13：原用全局单例 canonical_store，永远指向本服务
    # 默认库——非 default 库（如 std-water→standards 组）的表格在库范围内永远取不到）。
    canonical = docs_service._canonical_store_for(library_id)

    if not doc_ids:
        nodes = docs_service.list_nodes(library_id)
        doc_ids = [n.id for n in nodes if getattr(n, "type", "") == "document"]
    out: List[Dict[str, Any]] = []
    for doc_id in doc_ids:
        try:
            tables = canonical.list_tables(doc_id, limit=500)
        except Exception as exc:  # noqa: BLE001
            logger.warning("读取文档表格失败 doc_id=%s: %s", doc_id, exc)
            continue
        for table in tables:
            out.append({
                "doc_id": doc_id,
                "header_rows": table.header_rows,
                "rows": table.body_rows,
                "context": table.title or table.caption or table.summary or "",
                "page_idx": table.page_start,
            })
    return out
