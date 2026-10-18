"""枚举题预取（P1）：判定 → 改写查询 → 文档级检索 → 压瘦成 matter 卡 → 注入。

设计边界（2026-10-18 业主确认）：
- 只对「枚举意图」生效，普通问答零改动；
- 开关 ANGINEER_ENUM_PREFETCH 默认 0；
- 默认只对 ANGINEER_ENUM_PREFETCH_LIBRARIES 列出的库生效（默认 lab-firm-full，
  即评测库；"*" 表示全部库）；
- 任何一步失败都返回 None（降级为原链路），不允许成为新的失败点。

依据（P0/P0.5 离线实测，47 题）：
- 题面直搜 doc_search：真值 matter 召回 36.6%；
- 小模型改写 3 条短检索式：召回 92.8%（Qwen3.6-35B-A3B，47 题改写共 43 秒）；
- 卡片上限 80 张时 96.4%，但注入体积翻倍，默认取 60 张 / 12 KB。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CARDS = 40
MAX_CHARS = 12_000
_SNIPPET = 80

_EN_EVERY = re.compile(r"\b(every|each|list|enumerate)\b", re.I)
_EN_ALL = re.compile(
    r"\ball\b.{0,40}\b(matters?|documents?|deals?|cases?|clients?|files?|agreements?|items?|things?)\b",
    re.I,
)
_ZH_ENUM = re.compile(r"(所有|全部|每一个|每个|各个|有哪些|列出|枚举)")
_MCQ = re.compile(r"(^|\s)A[.、)]\s", re.M)

_REWRITE_PROMPT = """You turn a legal-research question into short keyword queries for a document search engine.

Question:
{question}

Return JSON only: {{"queries": ["...", "...", "..."]}}
Rules:
- 3 queries, each 2-5 words.
- Use concrete terms from the question: practice area, deal/document type, regulatory action.
- No generic words (matter, client, our, firm, please).
- Cover different angles, not three paraphrases.
"""


def enabled() -> bool:
    return os.getenv("ANGINEER_ENUM_PREFETCH", "0").strip().lower() in ("1", "true", "yes", "on")


def library_allowed(library_id: str) -> bool:
    """默认只允许评测库；配 "*" 才放开全部库。"""
    raw = os.getenv("ANGINEER_ENUM_PREFETCH_LIBRARIES", "lab-firm-full").strip()
    if not raw or raw == "*":
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return str(library_id or "") in allowed


def is_enumeration(query: str) -> bool:
    """枚举意图词面判定：宁严勿宽（误判会多花一次改写 + 12 KB 上下文）。"""
    text = str(query or "").strip()
    if len(text) < 8:
        return False
    if _MCQ.search(text):
        return False
    if _ZH_ENUM.search(text):
        return True
    if _EN_EVERY.search(text):
        return True
    return bool(_EN_ALL.search(text))


def rewrite_queries(
    llm: Any,
    query: str,
    *,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> List[str]:
    """一次小模型调用，压成 3 条短检索式；失败返回 []。"""
    from ai_inference.llm_client import chat_result_guarded
    from ai_inference.llm_response_parser import ParseError, extract_json_from_text

    messages = [{"role": "user", "content": _REWRITE_PROMPT.format(question=str(query)[:2000])}]
    try:
        result = chat_result_guarded(llm, messages, mode=mode, config_name=config_name, temperature=0.0)
        raw = result.text
    except Exception as exc:  # noqa: BLE001 —— 改写失败一律降级，不阻断问答
        logger.warning("enum_prefetch 改写失败: %s", exc)
        return []
    try:
        parsed = extract_json_from_text(raw, strict=True)
    except ParseError:
        try:
            parsed = extract_json_from_text(raw, strict=False)
        except ParseError:
            return []
    queries = parsed.get("queries") if isinstance(parsed, dict) else None
    if not isinstance(queries, list):
        return []
    return [str(q).strip() for q in queries if str(q).strip()][:4]


def _search_documents(library_id: str, query: str, *, limit: int, per_matter: int) -> Dict[str, Any]:
    from docs_core.step09_query.doc_search import search_documents

    return search_documents(library_id=library_id, query=query, limit=limit, per_matter=per_matter)


def _collect(library_id: str, queries: List[str]) -> "tuple[Dict[str, Dict[str, Any]], int]":
    """并集候选：matter_id → {title, snippet}；返回 (cards, 候选总数)。"""
    cards: Dict[str, Dict[str, Any]] = {}
    total = 0
    for query in queries:
        try:
            result = _search_documents(library_id, query, limit=120, per_matter=3)
        except Exception as exc:  # noqa: BLE001
            logger.warning("enum_prefetch 检索失败(%r): %s", query, exc)
            continue
        total = max(total, int(result.get("total_matters") or 0))
        for matter in result.get("matters") or []:
            mid = str(matter.get("matter_id") or "").strip()
            if not mid or mid in cards:
                continue
            best = matter.get("best") or {}
            cards[mid] = {
                "title": str(best.get("title") or ""),
                "snippet": " ".join(str(best.get("snippet") or "").split())[:_SNIPPET],
            }
    return cards, total


def format_context(cards: Dict[str, Dict[str, Any]], total_matters: int, queries: Optional[List[str]] = None) -> str:
    if os.getenv("ANGINEER_ENUM_PREFETCH_MODE", "cards").strip().lower() == "queries":
        # 只给检索式，不给候选卡：避免中文候选片段把英文作答带成中文、
        # 也避免模型把「候选里没有」当成「不存在」（2026-10-18 题 001 两版注入实测）。
        qs = "；".join(f'"{q}"' for q in (queries or [])[:4])
        return (
            "## Suggested search queries (system prefetch)\n"
            "This question asks for an exhaustive list. The system suggests these doc_search queries: "
            f"{qs}. Call doc_search with them (one call per query) before writing the answer."
        )
    lines = [
        "## 系统预取候选（文档级检索）",
        "本题判定为穷举型；以下是系统提前检索到的候选 matter，按 matter 归组。"
        "这不是结论，也不是用户提供的证据；需要时用 doc_read 读正文确认。",
    ]
    used = 0
    for mid, card in list(cards.items())[:MAX_CARDS]:
        line = f"- {mid} | {card['title']} | {card['snippet']}"
        if used + len(line) > MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    lines.append(f"候选 matter 共 {max(total_matters, len(cards))} 个；上面列出 {len(lines) - 3} 个。")
    return "\n".join(lines)


def build_enum_context(
    *,
    query: str,
    library_id: str,
    llm: Any,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    """开关 + 库白名单 + 枚举判定都通过时返回注入文本，否则 None。"""
    if not enabled() or not library_allowed(library_id):
        return None
    if not is_enumeration(query):
        return None
    queries = rewrite_queries(llm, query, config_name=config_name, mode=mode)
    if not queries:
        return None
    cards, total = _collect(library_id, queries)
    if not cards:
        return None
    text = format_context(cards, total, queries)
    logger.info("enum_prefetch 注入：queries=%s cards=%d chars=%d", queries, len(cards), len(text))
    return text
