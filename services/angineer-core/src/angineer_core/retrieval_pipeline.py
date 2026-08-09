"""检索流水线（P6b 从 dispatcher.py / retrieval_utils.py 下沉）。

承载多路召回（dense/sparse/table/formula/clause）→ Hybrid 融合 → 条件重排，
以及共享的引用构建 / 拒答校验 / 显式引用上下文 / 检索任务映射。
RetrieverAdapter 与 dispatcher 共用本模块，消除 P3 的临时共享函数文件。
"""
import logging
import os
import re
import time
from typing import Any, Dict, List, Tuple

logger = logging.getLogger(__name__)


def rerank_candidates(query: str, candidates: list, task_type: str = "") -> list:
    """用在线 reranker 服务重排序候选；未配置或失败时回退本地 phrase rerank。"""
    if len(candidates) <= 1:
        return candidates
    if not task_type.startswith("locate_") and len(candidates) <= 5:
        return candidates
    normalized_query = str(query or "").strip()
    from angineer_core.base_config import get_config

    cfg = get_config().dispatcher
    remote_url = str(cfg.reranker_url or "").strip().rstrip("/")
    if remote_url and not remote_url.endswith("/rerank"):
        remote_url = f"{remote_url}/v1/rerank"
    if not remote_url:
        from docs_core.step09_query.retrieval.reranker import rerank_candidates as local_rerank

        logger.debug("未配置在线 reranker（ANGINEER_RERANKER_URL），使用本地 phrase rerank")
        return local_rerank(normalized_query, task_type, candidates)
    timeout = cfg.reranker_timeout_sec
    try:
        import requests

        docs = [item.text or "" for item in candidates]
        headers = {}
        api_key = str(os.getenv("DOCS_RERANKER_API_KEY") or "").strip()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        resp = requests.post(
            remote_url,
            json={"query": query, "documents": docs, "top_n": len(candidates)},
            headers=headers or None,
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"reranker status {resp.status_code}")
        results = resp.json().get("results", [])
        if not results:
            raise RuntimeError("reranker empty results")
        score_map = {r["index"]: r["relevance_score"] for r in results}
        for i, item in enumerate(candidates):
            item.rerank_score = score_map.get(i, 0.0)
        candidates.sort(key=lambda item: item.rerank_score or 0.0, reverse=True)
        return candidates
    except Exception as exc:  # noqa: BLE001
        from docs_core.step09_query.retrieval.reranker import rerank_candidates as local_rerank

        logger.warning("远端 reranker 调用失败，回退到本地 phrase rerank: %s", exc)
        return local_rerank(normalized_query, task_type, candidates)


_KNOWN_STD_PREFIXES = frozenset({
    "JTS", "JTJ", "JT", "GB", "GBJ", "GB/T", "SL", "DL", "SY", "SH",
    "HG", "NB", "CJJ", "CJ", "TB", "YB", "JGJ", "JG", "DB",
})


def has_unsupported_reference(answer: str, evidence_text: str) -> bool:
    """检测答案中是否出现未在证据中出现的规范编号或题库背景引用。"""
    answer_text = str(answer or "")
    corpus = str(evidence_text or "")
    if not answer_text.strip():
        return False
    answer_std_names = set(re.findall(r"《([^》]+)》", answer_text))
    corpus_std_names = set(re.findall(r"《([^》]+)》", corpus))
    any_std_name_in_corpus = bool(answer_std_names & corpus_std_names)
    corpus_has_section_nums = bool(re.search(r"(?:第\s*)?\d+\.\d+", corpus))
    patterns = [
        r"[A-Z]{2,}\s*\d+(?:[-/]\d+)*(?:-\d{4})?",
        r"20\d{2}年[^\n，。；]*真题",
    ]
    for pat in patterns:
        for match in re.findall(pat, answer_text):
            token = str(match).strip()
            if not token or token in corpus:
                continue
            numeric_part = re.search(r"\d+(?:[-/]\d+)*(?:-\d{4})?", token)
            if numeric_part and numeric_part.group() in corpus:
                continue
            code_match = re.match(r"([A-Z]{2,})\s*(\d+)", token)
            if code_match:
                prefix = code_match.group(1)
                num = code_match.group(2)
                if prefix in corpus and num in corpus:
                    continue
                if prefix in _KNOWN_STD_PREFIXES and corpus_has_section_nums:
                    continue
            if any_std_name_in_corpus:
                continue
            return True
    return False


def build_citations_from_retrieved(fused, doc_nodes) -> list:
    """从检索结果构建 citations 数组（与 dispatcher 原实现一致）。"""
    from docs_core.docs_service import get_docs_service

    doc_title_map = {node.id: node.title for node in doc_nodes}
    docs_service = get_docs_service()
    citations = []
    for item in fused[:5]:
        doc_id = str(item.doc_id or "")
        citation_target_id = str(
            getattr(item, "citation_target_id", None)
            or item.metadata.get("citation_target_id")
            or item.item_id
            or ""
        ).strip()
        fusion_sources = item.metadata.get("fusion_sources", [])
        if not fusion_sources:
            source_kind = str(item.metadata.get("source_kind") or "")
            fusion_sources = [source_kind] if source_kind else []
        target = docs_service.get_citation_target(doc_id, citation_target_id) if citation_target_id else None
        if target:
            citations.append({
                "label": str(target.get("display_title") or item.title or "").strip(),
                "reference": {
                    "targetId": str(target.get("target_id") or citation_target_id),
                    "targetType": str(target.get("target_type") or item.entity_type or "content"),
                    "docId": doc_id,
                    "docTitle": doc_title_map.get(doc_id, ""),
                    "pageIdx": int(target.get("page_idx") or 0),
                    "pageLabel": target.get("page_label") or None,
                    "sectionPath": str(target.get("section_path") or ""),
                    "snippet": str(target.get("snippet") or item.text or "")[:200],
                },
                "score": float(item.rerank_score or item.score or 0.0),
                "fusion_sources": fusion_sources,
            })
            continue
        if not item.text:
            continue
        citations.append({
            "target_id": str(item.item_id or ""),
            "doc_id": doc_id,
            "doc_title": doc_title_map.get(doc_id, ""),
            "page_idx": int(item.metadata.get("page_idx", 0) or 0),
            "page_label": item.metadata.get("page_label") or None,
            "section_path": str(item.metadata.get("section_path") or ""),
            "snippet": str(item.text or "")[:200],
            "score": float(item.rerank_score or item.score or 0.0),
            "fusion_sources": fusion_sources,
        })
    return citations


def build_inline_citation_context(inline_citations: List[Dict[str, Any]]) -> str:
    """把前端显式确认的引用对象转成高优先级证据文本（与 dispatcher 同款，含富媒体摘要）。"""
    evidence_blocks: List[str] = []
    for item in inline_citations[:5]:
        reference = item.get("reference") if isinstance(item, dict) else {}
        if not isinstance(reference, dict):
            reference = {}
        label = str(item.get("label") or reference.get("label") or "").strip()
        doc_title = str(reference.get("docTitle") or reference.get("doc_title") or "").strip()
        section_path = str(reference.get("sectionPath") or reference.get("section_path") or "").strip()
        page_idx = reference.get("pageIdx", reference.get("page_idx", ""))
        content = str(reference.get("content") or reference.get("snippet") or "").strip()
        rich_media = reference.get("richMedia") or reference.get("rich_media") or {}
        rich_media_summary: List[str] = []
        if isinstance(rich_media, dict):
            if rich_media.get("tableHtml") or rich_media.get("table_html"):
                rich_media_summary.append("包含表格")
            if rich_media.get("mathContent") or rich_media.get("math_content"):
                rich_media_summary.append("包含公式")
            image_paths = rich_media.get("imagePaths") or rich_media.get("image_paths") or []
            if rich_media.get("imagePath") or rich_media.get("image_path") or image_paths:
                rich_media_summary.append("包含图片")
        meta_parts = [part for part in [
            f"标签: {label}" if label else "",
            f"文档: {doc_title}" if doc_title else "",
            f"页码: {page_idx}" if page_idx else "",
            f"位置: {section_path}" if section_path else "",
            f"富媒体: {'/'.join(rich_media_summary)}" if rich_media_summary else "",
        ] if part]
        block_parts = []
        if meta_parts:
            block_parts.append("\n".join(meta_parts))
        if content:
            block_parts.append(f"证据内容:\n{content}")
        if block_parts:
            evidence_blocks.append("\n".join(block_parts))
    return "\n---\n".join(evidence_blocks)


def map_intent_to_retriever_task(intent_result) -> str:
    """根据意图结果映射到检索任务类型。"""
    intent_level = str(getattr(intent_result, "intent_level", "") or "")
    intent_type = str(getattr(intent_result, "intent_type", "") or "")

    if intent_level == "L1":
        if "locate" in intent_type.lower():
            return "locate_qa"
        return "definition_qa"

    if intent_level == "L2":
        if "table" in intent_type.lower():
            return "table_qa"
        return "content_qa"

    return "content_qa"


def resolve_semantic_retriever_task(query: str, intent_result) -> str:
    """根据问句和意图结果选择更贴合的语义检索任务类型。"""
    normalized_query = str(query or "").strip()
    base_task_type = map_intent_to_retriever_task(intent_result)
    has_location_hint = any(
        token in normalized_query for token in ("哪一节", "哪一章", "哪一条", "在哪里", "在哪", "位于")
    )
    if has_location_hint and "公式" in normalized_query:
        return "locate_formula"
    if has_location_hint and "图" in normalized_query:
        return "locate_figure"
    if has_location_hint and "表" in normalized_query:
        return "locate_table"
    if base_task_type == "content_qa" and "公式" in normalized_query:
        return "formula_qa"
    return base_task_type


def run_semantic_retrieval(
    *,
    query: str,
    doc_nodes: list,
    library_id: str,
    doc_ids: List[str],
    task_type: str,
    filters=None,
    top_k_request: int = 10,
    top_k_fuse: int = 20,
) -> Tuple[list, Dict[str, Any], List[str], Dict[str, float]]:
    """多路召回（dense/sparse/table/formula/clause）→ Hybrid 融合 → 条件重排。

    返回 (fused, retrieval_debug, runtime_flags, timings)，与 dispatcher 原行为一致。
    """
    from docs_core.step09_query.protocols.contracts import KnowledgeQueryRequest
    from docs_core.step09_query.retrieval.clause_resolver import clause_resolver
    from docs_core.step09_query.retrieval.dense_retriever import dense_retriever
    from docs_core.step09_query.retrieval.formula_retriever import formula_retriever, is_formula_query
    from docs_core.step09_query.retrieval.sparse_retriever import sparse_retriever
    from docs_core.step09_query.retrieval.table_retriever import table_retriever
    from docs_core.step09_query.retrieval.hybrid_retriever import fuse_candidates

    _t1 = time.time()
    timings: Dict[str, float] = {}

    kq_request = KnowledgeQueryRequest(
        query=query,
        library_id=library_id,
        doc_ids=doc_ids,
        top_k=top_k_request,
        filters=filters,
    )
    dense_hits = dense_retriever.retrieve(
        kq_request, doc_nodes, task_type
    )
    runtime_flags = list(
        getattr(getattr(dense_retriever, "_embedding_provider", None), "runtime_flags", []) or []
    )
    retrieval_debug: Dict[str, Any] = {}
    if runtime_flags:
        retrieval_debug["runtime_flags"] = list(dict.fromkeys(runtime_flags))
    sparse_hits = sparse_retriever.retrieve(
        kq_request, doc_nodes, task_type
    )
    table_hits = table_retriever.retrieve(kq_request, doc_nodes)
    formula_hits = []
    if task_type in {"locate_formula", "formula_qa"} or is_formula_query(query, task_type):
        formula_hits = formula_retriever.retrieve(kq_request, doc_nodes)
    source_candidates = {
        "canonical_dense": dense_hits,
        "canonical_sparse": sparse_hits,
    }
    clause_hits = clause_resolver.retrieve(kq_request, doc_nodes, task_type)
    if clause_hits:
        source_candidates["clause_direct"] = clause_hits
    for item in formula_hits:
        source_kind = str(item.metadata.get("source_kind") or "formula_block")
        source_candidates.setdefault(source_kind, []).append(item)
    for item in table_hits:
        source_kind = str(
            item.metadata.get("source_kind") or "table_aware"
        )
        source_candidates.setdefault(source_kind, []).append(item)
    fused, retrieval_debug = fuse_candidates(
        source_candidates,
        task_type=task_type,
        top_k=top_k_fuse,
        filters=filters,
    )
    timings["retrieval"] = round(time.time() - _t1, 2)

    if len(fused) > 1 and (task_type.startswith("locate_") or len(fused) > 5):
        _t_rerank = time.time()
        fused = rerank_candidates(query, fused, task_type=task_type)
        timings["rerank"] = round(time.time() - _t_rerank, 2)
    return fused, retrieval_debug, runtime_flags, timings
