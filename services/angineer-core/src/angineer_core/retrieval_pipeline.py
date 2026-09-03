"""检索支撑：在线/本地 rerank 与答案拒绝校验（P6b 从旧 dispatcher.py / retrieval_utils.py 下沉）。

dense 语义通道降级（embedding 不可用）时，rerank 降级链为：
在线 reranker -> LLM 语义重排（本模块）-> 本地 phrase rerank。
"""
import re
from typing import Any, List, Optional

from ai_inference.llm_client import chat_result_guarded, get_llm_client
from ai_inference.llm_response_parser import extract_json_from_text
from angineer_core.base_logger import get_logger
from angineer_core.prompts.retrieval import LLM_RERANK_SYSTEM_PROMPT

logger = get_logger(__name__)


def llm_rerank_candidates(
    query: str,
    candidates: list,
    task_type: str = "",
    llm_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    top_n: int = 12,
    max_chars: int = 180,
) -> Optional[list]:
    """用 LLM 对候选做语义重排（dense 语义通道降级时的兜底）。

    只把前 top_n 条交给模型（控制成本），其余保持原序追加在末尾；
    返回重排后的列表；解析失败或结果无效返回 None，由调用方回退本地短语重排。
    """
    if not candidates:
        return []
    if len(candidates) <= 1:
        return candidates
    pool = list(candidates[:top_n])
    rest = list(candidates[top_n:])
    lines: List[str] = []
    for index, item in enumerate(pool):
        title = " ".join(str(getattr(item, "title", "") or "").split())[:60]
        text = " ".join(str(getattr(item, "text", "") or "").split())[:max_chars]
        lines.append(f"[{index}] {title}\n{text}")
    messages = [
        {"role": "system", "content": LLM_RERANK_SYSTEM_PROMPT},
        {"role": "user", "content": f"查询：{query}\n\n候选：\n" + "\n\n".join(lines)},
    ]
    client = llm_client if llm_client is not None else get_llm_client()
    try:
        result = chat_result_guarded(client, messages, mode=mode, config_name=config_name)
        parsed = extract_json_from_text(result.text, strict=True)
        raw_order = parsed.get("ranking") or []
        order: List[int] = []
        seen: set = set()
        for raw in raw_order:
            try:
                index = int(raw)
            except (TypeError, ValueError):
                continue
            if 0 <= index < len(pool) and index not in seen:
                seen.add(index)
                order.append(index)
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 语义重排失败，回退本地短语重排: %s", exc)
        return None
    if not order:
        logger.warning("LLM 语义重排未返回有效排序，回退本地短语重排")
        return None
    reranked = [pool[index] for index in order] + [
        pool[index] for index in range(len(pool)) if index not in seen
    ]
    total = len(reranked)
    for position, item in enumerate(reranked):
        item.rerank_score = round((total - position) / total, 6)
    reranked.extend(rest)
    return reranked


def rerank_candidates(
    query: str,
    candidates: list,
    task_type: str = "",
    dense_degraded: bool = False,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> list:
    """用在线 reranker 重排候选；未配置或失败时按降级链兜底。

    - dense 语义通道降级（dense_degraded=True）时优先尝试 LLM 语义重排；
    - 其余回退本地 phrase rerank。
    """
    if len(candidates) <= 1:
        return candidates
    if not task_type.startswith("locate_") and len(candidates) <= 5:
        return candidates
    normalized_query = str(query or "").strip()
    from angineer_core.base_config import get_config

    cfg = get_config().runner
    endpoints = list(cfg.reranker_configs or [])
    timeout = cfg.reranker_timeout_sec
    last_error: Optional[Exception] = None
    for index, endpoint in enumerate(endpoints):
        remote_url = str(endpoint.get("url") or "").strip().rstrip("/")
        if not remote_url:
            continue
        if not remote_url.endswith("/rerank"):
            remote_url = f"{remote_url}/v1/rerank"
        try:
            import requests

            docs = [item.text or "" for item in candidates]
            headers = {}
            api_key = str(endpoint.get("api_key") or "").strip()
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            endpoint_timeout = timeout
            if endpoint.get("timeout_sec") is not None:
                try:
                    endpoint_timeout = float(endpoint["timeout_sec"])
                except (TypeError, ValueError):
                    pass
            resp = requests.post(
                remote_url,
                json={"query": query, "documents": docs, "top_n": len(candidates)},
                headers=headers or None,
                timeout=endpoint_timeout,
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
            last_error = exc
            logger.warning(
                "reranker 端点 %d/%d 调用失败（%s），尝试下一端点: %s",
                index + 1,
                len(endpoints),
                endpoint.get("name") or remote_url,
                exc,
            )
    if endpoints:
        logger.warning("所有在线 reranker 端点均失败，进入降级链: %s", last_error)
    else:
        logger.debug("未配置在线 reranker（RERANKER_CONFIGS），使用降级链")

    if dense_degraded:
        llm_reranked = llm_rerank_candidates(
            normalized_query,
            candidates,
            task_type=task_type,
            config_name=config_name,
            mode=mode,
        )
        if llm_reranked is not None:
            logger.info("dense 语义通道降级，LLM 语义重排生效（%d 条候选）", len(candidates))
            return llm_reranked

    from docs_core.step09_query.retrieval.reranker import rerank_candidates as local_rerank

    logger.debug("回退本地 phrase rerank")
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
    answer_std_names = set(re.findall(r"《[^》]+》", answer_text))
    corpus_std_names = set(re.findall(r"《[^》]+》", corpus))
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
