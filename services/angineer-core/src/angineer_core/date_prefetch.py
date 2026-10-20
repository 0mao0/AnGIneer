"""日期预取（时间维度第二步）：判定「最新/最近」→ 改写检索式 → 按文档日期预取候选 → 注入。

设计边界（2026-10-20，承接 docs/plan-harvey-time-dimension.md §9.4）：
- 只对「最新/最近」意图生效，普通问答零改动；
- 开关 ANGINEER_DATE_PREFETCH 默认 0（P0.5 教训：预取注入默认关）；
- 复用 enum_prefetch 的改写口径（同一 prompt、同一降级策略），不新增模型协议；
- 任何一步失败都返回 None（降级为原链路）。

为什么需要它：评测里 16 道「最新/最近」题只有 4 题真的调了 doc_search(sort_by=date_desc)——
模型多数直接走 knowledge_search，日期参数进不了关键路径；本模块把「按日期排序的候选」
提前放到系统提示词里，让模型至少在决策时看到时间信号。

实测（2026-10-20 晚，16 题配对）：注入后日期参数使用率从 4/16 升到 11/16，但
criterion 反而从 14.0% 掉到 9.3%（4/43）——模型把预取候选当成「候选全集」，
不再自己检索，018/040/044/069 明显回落。**因此保持默认关，不启用**；
结论记入 docs/plan-harvey-time-dimension.md §10。
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional

from angineer_core.enum_prefetch import rewrite_queries

logger = logging.getLogger(__name__)

MAX_CARDS = 15
MAX_CHARS = 4000
_SNIPPET = 90

_ZH_DATE = re.compile(r"(最新|最近|最近一次|最近一笔|上一次|上一个|哪一年|截至|截止)")
_EN_DATE = re.compile(
    r"\b(latest|newest|most recent|most recently|last (?:one|deal|agreement|filing|issuance|transaction))\b",
    re.I,
)
_WORD_RE = re.compile(r"[0-9A-Za-z_\u4e00-\u9fff]+")


def enabled() -> bool:
    return os.getenv("ANGINEER_DATE_PREFETCH", "0").strip().lower() in ("1", "true", "yes", "on")


def library_allowed(library_id: str) -> bool:
    """默认放开全部库（开关本身默认关）；需要收窄时用逗号分隔库 id。"""
    raw = os.getenv("ANGINEER_DATE_PREFETCH_LIBRARIES", "*").strip()
    if not raw or raw == "*":
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return str(library_id or "") in allowed


def is_date_query(query: str) -> bool:
    """「最新/最近」意图词面判定：宁严勿宽（误判会多一次改写 + 4 KB 上下文）。"""
    text = str(query or "").strip()
    if len(text) < 6:
        return False
    return bool(_ZH_DATE.search(text) or _EN_DATE.search(text))


def _collect(library_id: str, queries: List[str]) -> "tuple[List[Dict[str, Any]], int]":
    """按日期降序并集：group → 最新一篇（usable 日期）。"""
    from docs_core.step09_query.doc_search import search_documents

    groups: Dict[str, Dict[str, Any]] = {}
    total = 0
    for query in queries:
        try:
            result = search_documents(
                library_id=library_id,
                query=query,
                limit=60,
                per_matter=2,
                sort_by="date_desc",
            )
        except Exception as exc:  # noqa: BLE001 —— 预取失败降级，不阻断问答
            logger.warning("date_prefetch 检索失败(%r): %s", query, exc)
            continue
        if result.get("error"):
            logger.info("date_prefetch 跳过：%s", result.get("error"))
            return [], 0
        total = max(total, int(result.get("total_groups") or result.get("total_matters") or 0))
        for card in result.get("matters") or []:
            gid = str(card.get("group_id") or card.get("matter_id") or "").strip()
            value = str(card.get("doc_date") or "")
            source = str(card.get("date_source") or "none")
            if not gid or not value or source == "mtime":
                continue
            best = card.get("best") or {}
            entry = {
                "group_id": gid,
                "matter_id": str(card.get("matter_id") or ""),
                "doc_date": value,
                "date_source": source,
                "date_confidence": str(card.get("date_confidence") or "none"),
                "title": str(best.get("title") or ""),
                "snippet": " ".join(str(best.get("snippet") or "").split())[:_SNIPPET],
            }
            current = groups.get(gid)
            if current is None or entry["doc_date"] > current["doc_date"]:
                groups[gid] = entry
    ordered = sorted(groups.values(), key=lambda x: (x["doc_date"], x["group_id"]), reverse=True)
    return ordered, total


def format_context(cards: List[Dict[str, Any]], total_groups: int, queries: List[str]) -> str:
    qs = "；".join(f'"{q}"' for q in queries[:3])
    lines = [
        "## 系统预取：按文档日期排序的候选（最新在前）",
        f"本题问「最新/最近」。系统已用 {qs} 做文档级检索，并按 doc_date 降序排列；"
        "日期来自正文首屏/文件名（mtime 已排除），可能不是签署日。",
        "用法：先按实体/案件挑出相关组，再用 doc_read 读正文核对落款日期与条款；"
        "候选不全，可用 doc_search(sort_by=\"date_desc\") 补查。这不是结论。",
    ]
    used = 0
    for card in cards[:MAX_CARDS]:
        line = (
            f"- {card['group_id']} | {card['doc_date']} | {card['date_source']}/{card['date_confidence']}"
            f" | {card['title']} | {card['snippet']}"
        )
        if used + len(line) > MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
    lines.append(f"候选组共 {max(total_groups, len(cards))} 个；上面列出 {min(len(cards), MAX_CARDS)} 个。")
    return "\n".join(lines)


def build_date_context(
    *,
    query: str,
    library_id: str,
    llm: Any = None,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    """开关 + 库白名单 + 日期意图都通过时返回注入文本，否则 None。"""
    if not enabled() or not library_allowed(library_id):
        return None
    if not is_date_query(query):
        return None
    queries = rewrite_queries(llm, query, config_name=config_name, mode=mode) if llm is not None else []
    if not queries:
        # 无改写（或改写失败）时退回题面的内容词，保证功能仍可用
        words = [w for w in _WORD_RE.findall(str(query or "")) if len(w) >= 2][:8]
        queries = [" ".join(words)] if words else []
    if not queries:
        return None
    cards, total = _collect(library_id, queries)
    if not cards:
        return None
    text = format_context(cards, total, queries)
    logger.info("date_prefetch 注入：queries=%s cards=%d chars=%d", queries, len(cards), len(text))
    return text
