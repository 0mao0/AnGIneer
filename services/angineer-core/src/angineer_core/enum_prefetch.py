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

import hashlib
import json
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
_EN_ACROSS = re.compile(r"\bacross\b.{0,80}\b(matters?|deals?|cases?|portfolio|practice)\b", re.I)
_EN_HOWMANY = re.compile(r"\bhow (often|many)\b", re.I)
_ZH_HOWMANY = re.compile(r"(多少次|多少个|几个|频率|占比)")
_MCQ = re.compile(r"(^|\s)A[.、)]\s", re.M)

# 目录谓词词表：问题里出现这些「文档类型/动作」词时，直接按文件名/标题过滤。
# 只收具体词，不收 matter/client/our 这类泛词；长词优先，避免 "second request" 被 "request" 抢走。
_CATALOG_TERMS = (
    "second request", "hsr withdrawal", "hsr", "withdrawal", "credit agreement",
    "assignment consent", "assignment", "tax opinion", "closing memo", "engagement letter",
    "purchase agreement", "loan agreement", "lease", "indemnity", "subpoena", "complaint",
    "settlement", "motion", "brief", "expert report", "diligence", "consent",
    "dip financing", "capital markets", "patent infringement", "technical expert",
    "use of proceeds", "leverage", "restructuring", "bankruptcy", "opinion", "proceeds",
    "二次问询", "问询函", "尽调", "意见书", "备忘录", "协议", "起诉", "和解",
)

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
    if _ZH_ENUM.search(text) or _ZH_HOWMANY.search(text):
        return True
    if _EN_EVERY.search(text):
        return True
    if _EN_ACROSS.search(text) or _EN_HOWMANY.search(text):
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


def _search_documents(library_id: str, query: str, *, limit: int, per_matter: int,
                      **kwargs: Any) -> Dict[str, Any]:
    """doc_search 包装（枚举检索线高参数经 kwargs 透传：max_matters/归组截断/窗口）。"""
    from docs_core.step09_query.doc_search import search_documents

    return search_documents(library_id=library_id, query=query, limit=limit,
                            per_matter=per_matter, **kwargs)


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
        text = (
            "## Suggested search queries (system prefetch)\n"
            "This question asks for an exhaustive list. The system suggests these doc_search queries: "
            f"{qs}. Call doc_search with them (one call per query) before writing the answer."
        )
        # P4 闭集约束：开守卫时同步给生成期要求，否则守卫会在回答后才把没读过的正确 matter 挪走。
        if os.getenv("ANGINEER_ENUM_CLOSED_SET", "0").strip().lower() in ("1", "true", "yes", "on"):
            text += (
                "\n\n## Closed-set requirement\n"
                "Only assert a matter as qualifying if you have read its source document with doc_read. "
                "Matters you did not read must go under a short section titled 'Not found in read evidence' — "
                "never present them as qualifying. Read representative documents of the candidate matters "
                "before writing the final answer."
            )
        return text
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


def catalog_phrases(query: str, limit: int = 3) -> List[str]:
    """从问题里抽目录谓词短语（确定性，不调模型）：长词优先、去重。"""
    flat = re.sub(r"[\s\-_]+", " ", str(query or "").lower())
    found: List[str] = []
    for term in sorted(_CATALOG_TERMS, key=len, reverse=True):
        norm = re.sub(r"[\s\-_]+", " ", term.lower())
        if len(norm) < 4 or norm in found:
            continue
        if norm in flat or (norm + "s") in flat:
            # 已被更长的词覆盖（如 "hsr" 被 "hsr withdrawal" 覆盖）就不重复加
            if any(norm in existing for existing in found):
                continue
            found.append(norm)
        if len(found) >= limit:
            break
    return found


def _catalog_cards(library_id: str, query: str, phrases: List[str]) -> "tuple[Dict[str, Dict[str, Any]], int]":
    """目录谓词 + 内容检索并集；按 group_id 归并（case/folder/doc 都适用）。"""
    from docs_core.step09_query.doc_search import search_documents

    cards: Dict[str, Dict[str, Any]] = {}
    total = 0

    def absorb(result: Dict[str, Any]) -> None:
        nonlocal total
        total = max(total, int(result.get("total_groups") or result.get("total_matters") or 0))
        for card in result.get("matters") or []:
            gid = str(card.get("group_id") or card.get("matter_id") or "").strip()
            if not gid or gid in cards:
                continue
            best = card.get("best") or {}
            cards[gid] = {
                "kind": str(card.get("group_kind") or ""),
                "title": str(best.get("title") or ""),
                "matched": list(card.get("matched_docs") or [])[:2],
            }

    for phrase in phrases[:3]:
        try:
            absorb(search_documents(
                library_id=library_id, query=phrase, limit=40, per_matter=2,
                filename_contains=[phrase],
            ))
        except Exception as exc:  # noqa: BLE001
            logger.warning("enum_prefetch 目录谓词失败(%r): %s", phrase, exc)
    try:
        absorb(search_documents(library_id=library_id, query=query, limit=40, per_matter=2))
    except Exception as exc:  # noqa: BLE001
        logger.warning("enum_prefetch 内容检索失败: %s", exc)
    return cards, total


def format_catalog_context(cards: Dict[str, Dict[str, Any]], total: int, phrases: List[str]) -> str:
    lines = [
        "## 系统预取候选（目录谓词）",
        f"本题判定为穷举型；系统按目录（文件名/标题/类型：{'、'.join(phrases)}）预取了候选组。",
        "这是线索，不是结论：确认资格必须用 doc_read 读正文。候选里没有的组不代表不存在，"
        "可用 doc_search 补查；不要因为候选不全而拒答。",
    ]
    used = 0
    shown = 0
    for gid, card in list(cards.items())[:MAX_CARDS]:
        extra = f" | {card['matched'][0]}" if card["matched"] else ""
        line = f"- {gid} | {card['kind'] or 'group'} | {card['title']}{extra}"
        if used + len(line) > MAX_CHARS:
            break
        lines.append(line)
        used += len(line)
        shown += 1
    lines.append(f"候选组共 {max(total, len(cards))} 个；上面列出 {shown} 个。")
    return "\n".join(lines)


# --- P4 代码预读（2026-10-22）：确定性读候选文档，注入真实片段 ---

PREREAD_MAX_MATTERS = 85  # 2026-11-07 提帽：041-1027 并集第 81 名（实测见预注册 §7）；016-1010@109 属排序质量，下一刀
PREREAD_CHARS = 1500
PREREAD_DEEP_CHARS = 4000
PREREAD_DEEP_MAX = 15
PREREAD_MAX_CONTEXT = 90_000


def preread_enabled() -> bool:
    return os.getenv("ANGINEER_ENUM_PREREAD", "0").strip().lower() in ("1", "true", "yes", "on")


def _fallback_query(question: str) -> str:
    """死查询兜底：题面前 10 个英文长词拼一条检索式（确定性、无领域知识、无 LLM）。"""
    return " ".join(re.findall(r"[A-Za-z]{4,}", str(question or ""))[:10])


def _preread_candidates(
    library_id: str, queries: List[str], question: str = ""
) -> Dict[str, Dict[str, Any]]:
    """改写式 → doc_search 取每个候选 matter 的代表文档（best.doc_id）＋第二代表文档。

    第二代表文档（docs[1]）不进第一遍摘录，只随 PREREAD INDEX 索引供二次加深
    「归类失败→换一篇文书重读」使用（2026-11-07 实测：016 细节文档常排组内第 2-3 篇，
    只重读同一篇更长文本救不动）。

    枚举检索线（2026-11-07，预注册 §7）：传高参数放开 doc_search 三层截断
    （matter 卡 80 / 归组 6000 / 窗口 4800——默认行为不变，仅本臂生效）；
    死查询（matters 为空）用题面长词兜底重试一次（041 的 q2/q3 语料级 0 命中实测）。
    """
    cards: Dict[str, Dict[str, Any]] = {}
    for query in queries:
        result: Dict[str, Any] = {}
        try:
            result = _search_documents(
                library_id, query, limit=120, per_matter=2,
                max_matters=80, group_candidates_cap=6000, window_rows=4800,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("enum_prefetch 预读检索失败(%r): %s", query, exc)
        if not result.get("matters") and question:
            # 死查询回退：改写式语料级 0 命中时，用题面词重试一次
            fb = _fallback_query(question)
            if fb and fb.strip().lower() != query.strip().lower():
                try:
                    result = _search_documents(
                        library_id, fb, limit=120, per_matter=2,
                        max_matters=80, group_candidates_cap=6000, window_rows=4800,
                    )
                    logger.info("enum_prefetch 死查询回退: %r -> %r (%d matters)",
                                query, fb[:60], len(result.get("matters") or []))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("enum_prefetch 死查询回退失败(%r): %s", fb, exc)
        for matter in result.get("matters") or []:
            mid = str(matter.get("matter_id") or "").strip()
            best = matter.get("best") or {}
            doc_id = str(best.get("doc_id") or "").strip()
            if not (mid and doc_id) or mid in cards:
                continue
            card: Dict[str, Any] = {
                "doc_id": doc_id,
                "title": str(best.get("title") or ""),
                # 跨查询最高分（响应无 score 的旧版本按 0 兜底，退化为首见序）
                "score": float(matter.get("score") or 0.0),
            }
            for entry in matter.get("docs") or []:
                alt = str((entry or {}).get("doc_id") or "").strip()
                if alt and alt != doc_id:
                    card["doc_id_2"] = alt
                    card["title_2"] = str((entry or {}).get("title") or "")
                    break
            cards[mid] = card
    if cards:
        # 并集按跨查询最高分降序（稳定）：首见序会让先发查询的低分 matter
        # 挤掉后发查询的金标（2026-11-07 实测：016 1008 在 q3 排 31 却被 union 序挤出）
        ordered = sorted(cards.items(), key=lambda kv: -kv[1].get("score", 0.0))
        cards = dict(ordered)
    return cards


def _read_excerpts(
    library_id: str, cards: Dict[str, Dict[str, Any]], question: str,
    excerpt_chars: int = 0,
) -> Dict[str, Any]:
    """批量 doc_read（match 模式）取每个候选的代表性段落；一个 matter 一条摘录。

    excerpt_chars>0 时自适应摘录长度（枚举检索线：matter 帽 50→70 后按
    85k 预算摊薄，深度损失由二次加深兜底——2026-11-07，预注册 §7）。
    """
    from docs_core.step09_query.doc_search import read_documents

    first_chars = int(excerpt_chars) if excerpt_chars and int(excerpt_chars) > 0 else PREREAD_CHARS
    items = list(cards.items())[:PREREAD_MAX_MATTERS]
    out: Dict[str, Any] = {}
    for start in range(0, len(items), 8):
        batch = items[start:start + 8]
        try:
            result = read_documents(
                library_id=library_id,
                doc_ids=[card["doc_id"] for _, card in batch],
                query=str(question or ""),
                max_chars_per_doc=first_chars,
                mode="match",
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("enum_prefetch 预读失败(batch %d): %s", start, exc)
            continue
        docs = {str(d.get("doc_id") or ""): d for d in result.get("docs") or []}
        for mid, card in batch:
            doc = docs.get(card["doc_id"]) or {}
            text = " ".join(str(doc.get("text") or "").split())
            if text:
                out[mid] = (card["title"], text[:first_chars])
    # 第二遍：摘录里一个查询词都没命中的 matter，按需加深到 4000 字符（封顶 15 个）
    terms = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", str(question or ""))][:10]
    if terms:
        deepen = [
            mid for mid, (_title, text) in out.items()
            if not any(term in text.lower() for term in terms)
        ][:PREREAD_DEEP_MAX]
        for start in range(0, len(deepen), 8):
            batch = [(mid, cards[mid]) for mid in deepen[start:start + 8] if mid in cards]
            if not batch:
                continue
            try:
                result = read_documents(
                    library_id=library_id,
                    doc_ids=[card["doc_id"] for _, card in batch],
                    query=str(question or ""),
                    max_chars_per_doc=PREREAD_DEEP_CHARS,
                    mode="match",
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("enum_prefetch 加深读失败(batch %d): %s", start, exc)
                continue
            docs = {str(d.get("doc_id") or ""): d for d in result.get("docs") or []}
            for mid, card in batch:
                doc = docs.get(card["doc_id"]) or {}
                text = " ".join(str(doc.get("text") or "").split())
                if text:
                    out[mid] = (card["title"], text[:PREREAD_DEEP_CHARS])
    return out


def _context_dump_key(query: str) -> str:
    """落盘文件键：题面空白归一后 sha1 前 12 位（dump 与 load 必须同一实现）。"""
    return hashlib.sha1(" ".join(str(query or "").split()).encode("utf-8")).hexdigest()[:12]


def _dump_enum_context(query: str, library_id: str, text: Optional[str]) -> None:
    """S2 实验通道：把本次预读注入原样落盘，供复用臂逐字节重放（best-effort）。"""
    dump_dir = os.getenv("ANGINEER_ENUM_CONTEXT_DUMP_DIR", "").strip()
    if not dump_dir or not text:
        return
    try:
        os.makedirs(dump_dir, exist_ok=True)
        payload = {"query": str(query), "library_id": str(library_id), "context": str(text)}
        path = os.path.join(dump_dir, f"enum_context_{_context_dump_key(query)}.json")
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        logger.info("enum_prefetch 上下文落盘: %s", path)
    except Exception as exc:  # noqa: BLE001 —— 落盘失败不得阻断问答
        logger.warning("enum_prefetch 上下文落盘失败: %s", exc)


def _load_dumped_context(query: str) -> Optional[str]:
    """S2 实验通道：命中落盘文件即逐字节复用（同候选同证据硬保证）；未命中走原链路。"""
    dump_dir = os.getenv("ANGINEER_ENUM_CONTEXT_DIR", "").strip()
    if not dump_dir:
        return None
    path = os.path.join(dump_dir, f"enum_context_{_context_dump_key(query)}.json")
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return None
    except Exception as exc:  # noqa: BLE001
        logger.warning("enum_prefetch 落盘上下文读取失败: %s", exc)
        return None
    text = str((data or {}).get("context") or "")
    if text:
        logger.info("enum_prefetch 复用落盘上下文: %s (chars=%d)", path, len(text))
        return text
    return None


def format_preread_context(
    excerpts: Dict[str, Any], doc_ids_map: Optional[Dict[str, Any]] = None,
    library_id: str = "", marker_allocator: Any = None,
) -> str:
    lines = [
        "## Pre-read evidence (system, deterministic)",
        "The system read the representative document of each candidate matter below.",
        "Judge qualification ONLY from these excerpts; do not rely on titles alone.",
    ]
    used = 0
    shown: List[str] = []
    for mid, (title, text) in excerpts.items():
        block = f"\n### {mid} | {title}\n{text}"
        if used + len(block) > PREREAD_MAX_CONTEXT:  # 预读注入上限 ~90k 字符
            break
        lines.append(block)
        used += len(block)
        shown.append(mid)
    if not shown:
        return ""
    lines.append("\nCLOSED SET (only these matters may be asserted as qualifying): " + ", ".join(shown))
    lines.append(
        "For each matter, assert it as qualifying only if its excerpt states the qualifying condition. "
        "Matters without such evidence must be listed under a short section titled 'Not qualified'."
    )
    # 索引行（机器行尾追加，evidence_blocks 的 CLOSED SET 切分天然把它排除在摘录外）：
    # doc_ids 供二次加深「归类失败→换篇重读」；cites 供 P0b ③引用贯通（渲染行 [K] 与
    # run_end.citations 同集，§1.3 契约）——编号来自 run 级 MarkerAllocator，与
    # knowledge_search 的 K 号同一命名空间、不重号。无 allocator 时不含 cites（向后兼容）。
    if doc_ids_map or marker_allocator is not None:
        index: Dict[str, Any] = {"library": str(library_id or "")}
        doc_index = {mid: doc_ids_map[mid] for mid in shown if mid in doc_ids_map}
        if doc_index:
            index["doc_ids"] = doc_index
        if marker_allocator is not None:
            index["cites"] = {mid: marker_allocator.next("K") for mid in shown}
        if len(index) > 1:
            lines.append("PREREAD INDEX (system): " + json.dumps(index, ensure_ascii=False, separators=(",", ":")))
    return "\n".join(lines)


def build_preread_context(
    *,
    library_id: str,
    query: str,
    llm: Any,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    marker_allocator: Any = None,
) -> Optional[str]:
    queries = rewrite_queries(llm, query, config_name=config_name, mode=mode) or [str(query)[:120]]
    cards = _preread_candidates(library_id, queries, question=str(query or ""))
    if not cards:
        return None
    # 自适应摘录长度：matter 帽 70 后按 85k 预算摊薄（70×1200≈84k < 90k 帽），
    # 深度损失由二次加深（兜底 matter 4000 字）补偿——枚举检索线，预注册 §7
    matter_n = max(1, min(len(cards), PREREAD_MAX_MATTERS))
    excerpt_chars = max(900, min(PREREAD_CHARS, 85_000 // matter_n))
    # 用第一条短检索式做读页定位（整句题面做 match 会稀释关键词）
    excerpts = _read_excerpts(library_id, cards, queries[0] if queries else str(query)[:120],
                              excerpt_chars=excerpt_chars)
    if not excerpts:
        return None
    doc_ids_map: Dict[str, Any] = {}
    for mid in excerpts:
        if mid not in cards:
            continue
        ids = [cards[mid]["doc_id"]]
        if cards[mid].get("doc_id_2"):
            ids.append(cards[mid]["doc_id_2"])
        doc_ids_map[mid] = ids if len(ids) > 1 else ids[0]
    text = format_preread_context(excerpts, doc_ids_map, library_id=library_id, marker_allocator=marker_allocator)
    logger.info("enum_prefetch(preread) 注入：matters=%d chars=%d", len(excerpts), len(text))
    return text or None


def build_enum_context(
    *,
    query: str,
    library_id: str,
    llm: Any,
    config_name: Optional[str] = None,
    mode: str = "instruct",
    marker_allocator: Any = None,
) -> Optional[str]:
    """开关 + 库白名单 + 枚举判定都通过时返回注入文本，否则 None。"""
    if not enabled() or not library_allowed(library_id):
        return None
    # S2 实验通道（plan-ls-routing §5.1 同候选同证据）：显式复用落盘上下文——
    # 命中即逐字节返回同一份预读注入，跳过改写+检索的采样不确定性；
    # 未命中按原链路走。文件来自 ANGINEER_ENUM_CONTEXT_DUMP_DIR 的落盘。
    reused = _load_dumped_context(query)
    if reused:
        return reused
    # 上下文门 = 枚举或聚合（plan-ls-routing §5.1 P0）：聚合题（how many/often、
    # share、breakdown）也要建预读候选全集，否则 S1/S2 两臂候选暴露不对等、配对破功
    # （016 题面无枚举词、只有聚合词，实证踩过）。聚合判定失败一律回退原门。
    try:
        from angineer_core.aggregate_answer import is_aggregation

        aggregation_query = is_aggregation(query)
    except Exception:  # noqa: BLE001
        aggregation_query = False
    if not is_enumeration(query) and not aggregation_query:
        return None
    if preread_enabled():
        text = build_preread_context(
            library_id=library_id, query=query, llm=llm, config_name=config_name, mode=mode,
            marker_allocator=marker_allocator,
        )
        _dump_enum_context(query, library_id, text)
        return text
    prefetch_mode = os.getenv("ANGINEER_ENUM_PREFETCH_MODE", "cards").strip().lower()
    if prefetch_mode == "catalog":
        try:
            from docs_core.step09_query.doc_search import catalog_predicate_usable

            if not catalog_predicate_usable(library_id):
                logger.info("enum_prefetch 跳过：目录质量不足 library=%s", library_id)
                return None
        except Exception as exc:  # noqa: BLE001
            logger.warning("enum_prefetch 目录门禁失败: %s", exc)
            return None
        phrases = catalog_phrases(query)
        if not phrases:
            return None
        cards, total = _catalog_cards(library_id, query, phrases)
        if not cards:
            return None
        text = format_catalog_context(cards, total, phrases)
        logger.info("enum_prefetch(catalog) 注入：phrases=%s cards=%d chars=%d", phrases, len(cards), len(text))
        return text
    queries = rewrite_queries(llm, query, config_name=config_name, mode=mode)
    if not queries:
        return None
    cards, total = _collect(library_id, queries)
    if not cards:
        return None
    text = format_context(cards, total, queries)
    logger.info("enum_prefetch 注入：queries=%s cards=%d chars=%d", queries, len(cards), len(text))
    return text
