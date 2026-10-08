"""检索支撑：在线/本地 rerank 与答案拒绝校验（P6b 从旧 dispatcher.py / retrieval_utils.py 下沉）。

dense 语义通道降级（embedding 不可用）时，rerank 降级链为：
在线 reranker -> LLM 语义重排（本模块）-> 本地 phrase rerank。

在线 rerank 成功后可叠加 LLM 二排（llm_second_rerank，ANGINEER_LLM_SECOND_RERANK 开启）：
wide pass 重排 top-N + duel 复核后才允许换掉第 1 名；replay 投影 hit@1(sec) 0.785→0.838
（scripts/rerank_replay.py，v4.1  nightly 冻结候选回放）。
"""
import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from ai_inference.llm_client import chat_result_guarded, get_llm_client
from ai_inference.llm_response_parser import extract_json_from_text
from angineer_core.base_logger import get_logger
from angineer_core.prompts.retrieval import (
    ADMISSION_SYSTEM_PROMPT,
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


# 上桌阈值与证据相关性标签档位对齐（_relevance_label / ANGINEER_EVIDENCE_GRADE_*）
ADMISSION_EXEMPT_RERANK = 0.6   # 头部豁免：rerank ≥0.6 免判直接进 listA（防判官误杀头部）
ADMISSION_QUARREL_RERANK = 0.3  # 吵架保留：判 0 但 rerank ≥0.3 保留进 listA 尾部（答案模型终裁）


def _admission_config_name() -> str:
    """上桌判官模型名（ANGINEER_ADMISSION_LLM_CONFIG）。默认对齐 llm2 条目（qwen3.8-flash-next，
    端点级 enable_thinking=false）。不复用 evals-core 的 EVAL_JUDGE_MODEL——跨包读取违反模块解耦红线。"""
    return os.environ.get("ANGINEER_ADMISSION_LLM_CONFIG", "").strip() or "Qwen3.8-Flash-Next"


def _extract_admission_json(text: str) -> Any:
    """判官文本 → JSON：先整段 json.loads（裸数组 [{i,keep}] 形态——
    extract_json_from_text 会把裸数组剪成首个 {..} 片段必炸），失败再交它兜 fenced/对象形态。"""
    try:
        return json.loads(str(text or "").strip())
    except (TypeError, ValueError):
        return extract_json_from_text(text, strict=True)


def _parse_admission_verdicts(parsed: Any, total: int) -> Optional[Dict[int, bool]]:
    """判官输出 → {下标: keep}；不可解析返回 None（由调用方 fail-open）。

    接受裸数组 [{"i":0,"keep":1},…] 或包一层的对象（admission/decisions/items/results 任一键）。
    缺席的条目按「判 1 放宽」语义视为 keep（漏答≠确定无关）。"""
    if isinstance(parsed, dict):
        for key in ("admission", "decisions", "items", "results"):
            if isinstance(parsed.get(key), list):
                parsed = parsed[key]
                break
        else:
            return None
    if not isinstance(parsed, list):
        return None
    verdicts: Dict[int, bool] = {}
    for entry in parsed:
        if not isinstance(entry, dict):
            continue
        try:
            index = int(entry.get("i"))
        except (TypeError, ValueError):
            continue
        if not 0 <= index < total:
            continue
        raw_keep = entry.get("keep")
        if isinstance(raw_keep, str):
            keep = raw_keep.strip().lower() in ("1", "true", "yes")
        else:
            keep = bool(raw_keep)
        verdicts[index] = keep
    if not verdicts:
        return None
    return verdicts


def admit_evidence(
    query: str,
    candidates: list,
    *,
    llm_client: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> "tuple[list, Dict[str, Any]]":
    """证据上桌（LLM 定员出 listA，plan-evidence-admission §1）：批量一枪 0/1 判，禁逐条连调。

    输入 rerank 截断后的 top15；每条摘录 ≤ANGINEER_ADMISSION_EXCERPT_CHARS（默认 1000）字符。
    规则：rerank ≥0.6 头部豁免免判直接进桌；判 1 进主桌；判 0 且 ≥0.3 吵架保留进桌尾；
    判 0 且 <0.3 一致丢弃；判官缺席条目按判 1 放宽处理。
    listA 空（判官全 0 且无豁免无吵架）→ 返回空列表，由调用方走标准拒答，**不回退**。
    判官异常/超时/输出不可解析 → fail-open 全量放行（fallback=True，计数置 None），永不过滤层打死回答。
    返回 (listA, admission_block)——block 八字段留痕，cap_dropped 由装配末端合并时填。
    """
    judge_config = config_name or _admission_config_name()

    def _fail_open(reason: str, judge_ms: Optional[int] = None):
        logger.warning("证据上桌判官 fail-open（%s），%d 条全量放行", reason, len(candidates))
        return list(candidates), {
            "kept": None, "dropped": None, "quarreled": None, "exempted": None,
            "fallback": True, "judge_config": judge_config, "judge_ms": judge_ms,
        }

    if not candidates:
        return [], {
            "kept": 0, "dropped": 0, "quarreled": 0, "exempted": 0,
            "fallback": False, "judge_config": judge_config, "judge_ms": 0,
        }
    excerpt_chars = max(100, _env_int("ANGINEER_ADMISSION_EXCERPT_CHARS", 1000))
    lines: List[str] = []
    for index, item in enumerate(candidates):
        title = " ".join(str(getattr(item, "title", "") or "").split())[:60]
        text = " ".join(str(getattr(item, "text", "") or "").split())[:excerpt_chars]
        lines.append(f"[{index}] {title}\n{text}")
    messages = [
        {"role": "system", "content": ADMISSION_SYSTEM_PROMPT},
        {"role": "user", "content": f"问题：{query}\n\n候选证据：\n\n" + "\n\n".join(lines)},
    ]
    client = llm_client if llm_client is not None else get_llm_client()
    _t = time.perf_counter()
    try:
        result = chat_result_guarded(
            client, messages, mode=mode, config_name=judge_config, max_tokens=512,
        )
        parsed = _extract_admission_json(result.text)
    except Exception as exc:  # noqa: BLE001
        return _fail_open(f"调用失败: {str(exc)[:200]}", int((time.perf_counter() - _t) * 1000))
    judge_ms = int((time.perf_counter() - _t) * 1000)
    verdicts = _parse_admission_verdicts(parsed, len(candidates))
    if verdicts is None:
        return _fail_open("输出不可解析", judge_ms)

    main: List[Any] = []
    quarreled: List[Any] = []
    kept = exempted = quarreled_n = dropped = 0
    for index, item in enumerate(candidates):
        try:
            score = float(getattr(item, "rerank_score", None) or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score >= ADMISSION_EXEMPT_RERANK:
            main.append(item)
            exempted += 1
        elif verdicts.get(index, True):
            main.append(item)
            kept += 1
        elif score >= ADMISSION_QUARREL_RERANK:
            quarreled.append(item)
            quarreled_n += 1
        else:
            dropped += 1
    list_a = main + quarreled
    if not list_a:
        logger.info("证据上桌空桌（判官全 0 且无豁免/吵架条）：%d 条全弃，走标准拒答不回答", len(candidates))
    else:
        logger.info(
            "证据上桌：入桌 %d/%d（判1=%d 豁免=%d 吵架=%d）丢弃 %d，judge=%s %dms",
            len(list_a), len(candidates), kept, exempted, quarreled_n, dropped, judge_config, judge_ms,
        )
    return list_a, {
        "kept": kept, "dropped": dropped, "quarreled": quarreled_n, "exempted": exempted,
        "fallback": False, "judge_config": judge_config, "judge_ms": judge_ms,
    }


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


def _norm_book_title(text: str) -> str:
    """书名号匹配归一：剥书名号括弧、去全部空白、忽略大小写（跨行折行/大小写变体容错）。"""
    return re.sub(r"[\s《》]+", "", str(text or "")).casefold()


def _has_verifiable_section_ref(answer: str, corpus: str) -> bool:
    """答案「第"X"章/节/条」引用在证据中可核：归一化全文命中或数字链（X.Y+）命中即算。

    两种形态：带引号的章节名（第"1. Introduction"章节）与裸数字条款（第3.1节）。
    """
    answer_text = str(answer or "")
    refs = re.findall(r"第\s*[“\"]([^”\"]{1,80})[”\"]\s*[章节条]", answer_text)
    refs += re.findall(r"第\s*(\d+(?:\.\d+)+)\s*[章节条]", answer_text)
    corpus_norm = _norm_book_title(corpus)
    for ref in refs:
        ref_text = str(ref).strip()
        if not ref_text:
            continue
        ref_norm = _norm_book_title(ref_text)
        if ref_norm and ref_norm in corpus_norm:
            return True
        num = re.match(r"(\d+\.\d+(?:\.\d+)*)", ref_text)
        if num and num.group(1) in corpus:
            return True
    return False


def _absent_book_titles(answer: str, corpus: str) -> "list[str]":
    """答案《》标题里逐条核不到证据面的（归一化子串判定，与书名号闸同口径）。"""
    std_names = re.findall(r"《[^》]+》", str(answer or ""))
    if not std_names:
        return []
    haystack = _norm_book_title(corpus)
    return [t for t in std_names if _norm_book_title(t) not in haystack]


_URGENT_MARK = "⚠️出处待核"


def _strip_absent_citations(answer: str, titles: "list[str]") -> str:
    """把核不到的《标题》引用从答案里摘除，正文句子保留。

    v16 出处句式「根据《X》第Y节」里，《X》只是句首状语：整句删除会连事实一起丢
    （2026-10-07/08 两晚 30+ 题好答案整答换拒答的根因）。只删标题及其紧邻的引导介词；
    章节号无标题悬空时补 ⚠️出处待核，保留「出处不实」信号。
    逐处替换按原始字符串匹配，A|AB 类包含关系不会误伤可核到的标题。
    """
    text = str(answer or "")
    for title in titles:
        text = re.sub(r"(?:根据|依据|按照|参照)?\s*" + re.escape(title), "", text)
    # 章/节后紧跟的「（⚠️出处待核）」说明括注去重（标题剥除后括注即悬空标记）
    text = re.sub(r"([章节条])\s*[（(]\s*" + _URGENT_MARK + r"\s*[)）]", r"\1", text)
    # 剥除后以「第X节/章」悬空开头的句子补待核标记
    text = re.sub(
        r"(?:^|(?<=[。；;！!？?\n]))\s*(第[0-9一二三四五六七八九十]+(?:\.\d+)*[章节条])",
        r"\1（" + _URGENT_MARK + r"）",
        text,
    )
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


def find_unsupported_reference(answer: str, evidence_text: str) -> "tuple[str, list[str]]":
    """出处守卫三态判定：(verdict, 核不到的标题列表)。

    - "hard"：编造规范编号/题库背景（2026-10-07 守卫标题软化后遗留的可达敞口），
      维持整答替换拒答；
    - "strip"：答案《》标题全部核不到、且章节引用也不可信——外部文献名引用形态
      （OpenRAG 论文真题名对不上 doc_title=文件名），降为剥标记保留正文，不整答替换
      （2026-10-08 方案A，业主拍板；两晚误杀 30+ 题好答案）；
    - "clean"：放行。
    """
    answer_text = str(answer or "")
    corpus = str(evidence_text or "")
    if not answer_text.strip():
        return ("clean", [])
    answer_std_names = set(re.findall(r"《[^》]+》", answer_text))
    corpus_std_names = set(re.findall(r"《[^》]+》", corpus))
    any_std_name_in_corpus = bool(answer_std_names & corpus_std_names)
    strip_titles: "list[str]" = []
    # 《》书名号闸（2026-10-07）：答案引用的标题在证据里全部核不到才进入嫌疑；
    # 部分核到即放行——论文真题名/中译名等次级引用是合法形态，逐条硬拦会误杀真答案
    # （2026-10-07 1040 全集实测：981 条《》引用 0 硬编造，变体 4 条均混有可核到的在库标题）。
    # 在库标题经装配前缀《doc_title》落在 items[].text（agent_tools 检索后装配），守卫证据面天然含标题。
    if answer_std_names:
        title_haystack = _norm_book_title(corpus)
        if not any(_norm_book_title(t) in title_haystack for t in answer_std_names):
            # 方案 B 软化（2026-10-07 夜班 OpenRAG -2.6pp 回归实锤）：标题全核不到不当场判死——
            # 答案引用的章节/条款号能在证据里核到即放行。误杀形态＝答案引论文真题名而证据
            # doc_title 是文件名（2404.09358v3.pdf），24 题好答案被替换拒答。
            # 全核不到且章节也不可信时不再整答替换（2026-10-08 方案A）：转入 strip，
            # 下方的规范编号检查独立兜底，真编造编号照样拦（hard 优先于 strip）。
            if not _has_verifiable_section_ref(answer_text, corpus):
                strip_titles = _absent_book_titles(answer_text, corpus)
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
            return ("hard", [])
    if strip_titles:
        return ("strip", strip_titles)
    return ("clean", [])


def has_unsupported_reference(answer: str, evidence_text: str) -> bool:
    """检测答案中是否出现未在证据中出现的规范编号或题库背景引用。

    2026-10-08 方案A 起等价于「三态判定为 hard」：外部文献名引用（标题全核不到）
    不再判 True，由守卫剥标记分支处理（见 find_unsupported_reference / make_final_answer_guard）。
    """
    return find_unsupported_reference(answer, evidence_text)[0] == "hard"
