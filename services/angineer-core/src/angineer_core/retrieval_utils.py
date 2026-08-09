"""语义检索共享工具函数（P3 抽取，P6 将归位 retrieval_pipeline）。

从 dispatcher 抽出，保持行为一致：rerank 候选、答案引用校验、引用数组构建。
"""
import logging
import os
import re
from typing import Any, Dict, List

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
