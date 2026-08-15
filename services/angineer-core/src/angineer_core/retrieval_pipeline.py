"""检索支撑：在线/本地 rerank 与答案拒答校验（P6b 从旧 dispatcher.py / retrieval_utils.py 下沉）。"""
import logging
import os
import re

logger = logging.getLogger(__name__)


def rerank_candidates(query: str, candidates: list, task_type: str = "") -> list:
    """用在线 reranker 服务重排序候选；未配置或失败时回退本地 phrase rerank。"""
    if len(candidates) <= 1:
        return candidates
    if not task_type.startswith("locate_") and len(candidates) <= 5:
        return candidates
    normalized_query = str(query or "").strip()
    from angineer_core.base_config import get_config

    cfg = get_config().runner
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
