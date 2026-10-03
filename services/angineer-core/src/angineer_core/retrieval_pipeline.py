"""检索支撑：在线/本地 rerank 与答案拒绝校验（P6b 从旧 dispatcher.py / retrieval_utils.py 下沉）。

dense 语义通道降级（embedding 不可用）时，rerank 降级链为：
在线 reranker -> LLM 语义重排（本模块）-> 本地 phrase rerank。

在线 rerank 成功后可叠加 LLM 二排（llm_second_rerank，ANGINEER_LLM_SECOND_RERANK 开启）：
wide pass 重排 top-N + duel 复核后才允许换掉第 1 名；replay 投影 hit@1(sec) 0.785→0.838
（scripts/rerank_replay.py，v4.1  nightly 冻结候选回放）。
"""
import os
import re
import time
from typing import Any, List, Optional

from ai_inference.llm_client import chat_result_guarded, get_llm_client
from ai_inference.llm_response_parser import extract_json_from_text
from angineer_core.base_logger import get_logger
from angineer_core.prompts.retrieval import (
    LLM_RERANK_DEF_SYSTEM_PROMPT,
    LLM_RERANK_DUEL_SYSTEM_PROMPT,
    LLM_RERANK_SYSTEM_PROMPT,
)

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


def _second_rerank_enabled() -> bool:
    return os.environ.get("ANGINEER_LLM_SECOND_RERANK", "0").strip().lower() in ("1", "true", "on")


def estimated_rerank_wait_seconds() -> float:
    """在线 rerank 走完全部端点的超时预算（memo 在途等待上限的组成项，agent_tools 消费）。

    rerank_candidates 是逐端点循环（retrieval_pipeline.py:249-307），预算必须按端点循环
    总时长算，不是单个超时值（施工单 v3.2 变更 A 等待预算公式）。"""
    from angineer_core.base_config import get_config

    cfg = get_config().runner
    endpoints = list(cfg.reranker_configs or [])
    if not endpoints:
        return 0.0
    total = 0.0
    for endpoint in endpoints:
        ep_timeout = endpoint.get("timeout_sec") if isinstance(endpoint, dict) else None
        try:
            total += float(ep_timeout) if ep_timeout is not None else float(cfg.reranker_timeout_sec)
        except (TypeError, ValueError):
            total += float(cfg.reranker_timeout_sec)
    return total


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


def _llm_rank_order(
    query: str,
    candidates: list,
    *,
    prompt: str,
    top_n: int,
    max_chars: int,
    llm_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[List[int]]:
    """让 LLM 给前 top_n 条候选排序，返回候选下标顺序；失败返回 None。"""
    pool = list(candidates[:top_n])
    lines: List[str] = []
    for index, item in enumerate(pool):
        title = " ".join(str(getattr(item, "title", "") or "").split())[:60]
        text = " ".join(str(getattr(item, "text", "") or "").split())[:max_chars]
        lines.append(f"[{index}] {title}\n{text}")
    messages = [
        {"role": "system", "content": prompt},
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
        logger.warning("LLM 重排调用失败: %s", exc)
        return None
    if not order:
        return None
    return order + [i for i in range(len(pool)) if i not in set(order)]


def _llm_duel(
    query: str,
    champion: Any,
    challenger: Any,
    *,
    max_chars: int,
    llm_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[bool]:
    """两条候选全文对决，challenger 胜返回 True；无法判定返回 None。"""
    def _fmt(item: Any) -> str:
        title = " ".join(str(getattr(item, "title", "") or "").split())[:60]
        text = " ".join(str(getattr(item, "text", "") or "").split())[:max_chars]
        return f"{title}\n{text}"

    messages = [
        {"role": "system", "content": LLM_RERANK_DUEL_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"查询：{query}\n\n候选A：\n{_fmt(champion)}\n\n候选B：\n{_fmt(challenger)}")},
    ]
    client = llm_client if llm_client is not None else get_llm_client()
    try:
        result = chat_result_guarded(client, messages, mode=mode, config_name=config_name)
        parsed = extract_json_from_text(result.text, strict=True)
        winner = str(parsed.get("winner") or "").strip().upper()
    except Exception as exc:  # noqa: BLE001
        logger.warning("LLM 二排 duel 调用失败: %s", exc)
        return None
    if winner == "B":
        return True
    if winner == "A":
        return False
    return None


def llm_second_rerank(
    query: str,
    candidates: list,
    *,
    llm_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> list:
    """在线 rerank 后的 LLM 二排：wide pass 重排 top-N，duel 复核通过才允许换掉第 1 名。

    任何一步失败都原样返回 candidates（不改变序、不改分），保证零回归兜底。
    """
    if not candidates or len(candidates) <= 1:
        return candidates
    top_n = max(2, _env_int("ANGINEER_LLM_SECOND_RERANK_TOP_N", 15))
    max_chars = max(200, _env_int("ANGINEER_LLM_SECOND_RERANK_MAX_CHARS", 1500))
    duel_chars = max(200, _env_int("ANGINEER_LLM_SECOND_RERANK_DUEL_MAX_CHARS", 4000))
    order = _llm_rank_order(
        query, candidates,
        prompt=LLM_RERANK_DEF_SYSTEM_PROMPT,
        top_n=min(top_n, len(candidates)),
        max_chars=max_chars,
        llm_client=llm_client,
        config_name=config_name,
        mode=mode,
    )
    if not order or order[0] == 0:
        return candidates
    challenger_wins = _llm_duel(
        query,
        candidates[0],
        candidates[order[0]],
        max_chars=duel_chars,
        llm_client=llm_client,
        config_name=config_name,
        mode=mode,
    )
    if not challenger_wins:
        logger.info("LLM 二排 duel 否决覆盖（候选 #%s 未能击败原第 1 名）", order[0])
        return candidates
    reranked = [candidates[i] for i in order] + list(candidates[len(order):])
    total = len(reranked)
    for position, item in enumerate(reranked):
        item.rerank_score = round((total - position) / total, 6)
    logger.info("LLM 二排 duel 确认覆盖：候选 #%s 升为第 1 名", order[0])
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
            if _second_rerank_enabled():
                _t2 = time.perf_counter()
                candidates = llm_second_rerank(
                    normalized_query,
                    candidates,
                    config_name=config_name,
                    mode=mode,
                )
                logger.info("LLM 二排计时: %.2fs candidates=%d", time.perf_counter() - _t2, len(candidates))
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

    from angineer_core import ports

    local_rerank = ports.get_local_rerank()
    if local_rerank is None:
        # 引擎不再 import 检索实现包；未注册时降级为原样返回（候选顺序即 dense/sparse 融合序），
        # 与 reranker 全链失败的语义一致——不 crash、不 import 具体包
        logger.warning("local_rerank 未注册（组装层应注入 docs-core 适配器），跳过 phrase rerank")
        return candidates

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
