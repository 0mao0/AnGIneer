"""P2.1 证据绑定（离线审计版）：答案 → 断言+引文 → 逐条核验 → 剔掉无依据的句子。

设计边界：
- 开关 ANGINEER_EVIDENCE_BIND 默认 0；只作为后置审计，不改生成模板；
- 核验只对照「本轮工具实际返回的文本」，不查库、不重新检索；
- 引文要求逐字（归一化后）出现在证据里，长度 ≥ 30；不满足即判「无依据」；
- 只删「无依据断言」所在的句子，不改写其余内容；
- 抽取用的 LLM 调用失败/JSON 不合法 → 原样返回，不阻断。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_QUOTE = 30
MAX_EVIDENCE_CHARS = 24_000
_SENT_SPLIT = re.compile(r"(?<=[。！？.!?])\s+|\n+")
_MATTER_ID = re.compile(r"\b\d{4}-\d{5}\b")

_EXTRACT_PROMPT = """You audit an answer against the evidence its agent actually retrieved.

Answer:
{answer}

Evidence (doc_id | text):
{evidence}

Return JSON only:
{{"claims": [{{"claim": "one factual assertion from the answer", "doc_id": "doc id from evidence", "quote": "verbatim text from that doc supporting the claim"}}]}}

Rules:
- Max 20 claims; only checkable factual assertions (names, numbers, dates, statuses).
- "quote" must be copied verbatim from the evidence text, 30+ characters, no paraphrase.
- If the answer has no evidence-backed assertion, return {{"claims": []}}.
"""


def enabled() -> bool:
    return os.getenv("ANGINEER_EVIDENCE_BIND", "0").strip().lower() in ("1", "true", "yes", "on")


def _norm(text: str) -> str:
    text = str(text or "").lower()
    text = re.sub(r"[\s\u3000]+", " ", text)
    text = re.sub(r"[\"'“”‘’`*_#>\[\]]", "", text)
    return text.strip()


def collect_evidence(messages: List[Any]) -> List[Dict[str, str]]:
    """从工具消息里抽可引用的原文：knowledge_search.items / doc_read.docs / doc_search.matters。"""
    out: List[Dict[str, str]] = []
    for m in messages:
        if getattr(m, "role", "") != "tool":
            continue
        try:
            raw = json.loads(getattr(m, "content", "") or "{}")
        except Exception:  # noqa: BLE001
            continue
        if not isinstance(raw, dict):
            continue
        for item in raw.get("items") or []:
            if isinstance(item, dict) and item.get("text"):
                out.append({"doc_id": str(item.get("doc_id") or ""), "text": str(item["text"])})
        for doc in raw.get("docs") or []:
            if isinstance(doc, dict) and doc.get("text"):
                out.append({"doc_id": str(doc.get("doc_id") or ""), "text": str(doc["text"])})
        for matter in raw.get("matters") or []:
            best = matter.get("best") or {}
            if best.get("snippet"):
                out.append({"doc_id": str(best.get("doc_id") or matter.get("matter_id") or ""),
                            "text": str(best["snippet"])})
    return out


def quote_supported(quote: str, evidence: List[Dict[str, str]]) -> bool:
    """引文是否逐字出现在某条证据里（允许省略号分段）。"""
    q = _norm(quote)
    if len(q) < MIN_QUOTE:
        return False
    parts = [p for p in re.split(r"…+|\.\.\.", q) if len(p.strip()) >= 15]
    if not parts:
        parts = [q]
    for ev in evidence:
        text = _norm(ev.get("text") or "")
        if text and all(part in text for part in parts):
            return True
    return False


def verify_claims(claims: List[Dict[str, Any]], evidence: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    out = []
    for c in claims:
        quote = str(c.get("quote") or "")
        ok = quote_supported(quote, evidence)
        out.append({**c, "supported": ok})
    return out


def strip_unsupported(answer: str, claims: List[Dict[str, Any]]) -> "tuple[str, int]":
    """删掉含「无依据断言」关键标识的句子；没有可定位标识时不动。"""
    bad = [c for c in claims if not c.get("supported")]
    if not bad:
        return answer, 0
    keys: List[str] = []
    for c in bad:
        keys += _MATTER_ID.findall(str(c.get("claim") or ""))
        q = str(c.get("quote") or "")
        keys += [w for w in re.findall(r"[A-Za-z][\w\-]{6,}", q)[:2]]
    keys = [k for k in dict.fromkeys(keys) if k]
    if not keys:
        return answer, 0
    sentences = [s for s in _SENT_SPLIT.split(answer) if s is not None]
    kept, removed = [], 0
    for s in sentences:
        if s and any(k.lower() in s.lower() for k in keys):
            removed += 1
            continue
        kept.append(s)
    if not removed:
        return answer, 0
    text = "\n\n".join(p.strip() for p in kept if p.strip())
    return (text or answer), removed


def make_guard(inner: Any, *, llm: Any, config_name: Optional[str] = None, mode: str = "instruct"):
    """包在既有 guard 外侧：先跑原 guard，再对最终答案做证据绑定审计。"""

    def guard(added_messages: List[Any]):
        base = inner(added_messages) if inner is not None else None
        if isinstance(base, tuple) and len(base) >= 2:
            answer = str(base[0] or "")
        elif isinstance(base, str):
            answer = base
        else:
            final = next(
                (m for m in reversed(added_messages) if getattr(m, "role", "") == "assistant"
                 and not getattr(m, "tool_calls", None)),
                None,
            )
            answer = str(getattr(final, "content", "") or "") if final else ""
        if not answer:
            return base
        evidence = collect_evidence(added_messages)
        audit = audit_answer(llm, answer, evidence, config_name=config_name, mode=mode)
        if not audit["claims"]:
            logger.info("evidence_bind: 无可核断言（claims=0），答案原样")
            return base
        new_text, removed = strip_unsupported(answer, audit["claims"])
        logger.info(
            "evidence_bind: claims=%d supported=%d unsupported=%d removed_sentences=%d",
            len(audit["claims"]), audit["supported"], audit["unsupported"], removed,
        )
        if not removed:
            return base
        return (new_text, f"证据绑定：移除 {removed} 句无依据断言", "evidence_rebound")

    return guard


def audit_answer(
    llm: Any,
    answer: str,
    evidence: List[Dict[str, str]],
    *,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Dict[str, Any]:
    """一次 LLM 抽取 + 规则核验；任何异常返回空 claims。"""
    if not answer or not evidence:
        return {"claims": [], "supported": 0, "unsupported": 0}
    ev_text = "\n".join(
        f"{e['doc_id']} | {e['text'][:1200]}" for e in evidence[:40]
    )[:MAX_EVIDENCE_CHARS]
    prompt = _EXTRACT_PROMPT.format(answer=answer[:8000], evidence=ev_text)
    from ai_inference.llm_client import chat_result_guarded
    from ai_inference.llm_response_parser import ParseError, extract_json_from_text

    try:
        result = chat_result_guarded(
            llm, [{"role": "user", "content": prompt}], mode=mode,
            config_name=config_name, temperature=0.0,
        )
        raw = result.text
    except Exception as exc:  # noqa: BLE001
        logger.warning("evidence_bind 抽取失败: %s", exc)
        return {"claims": [], "supported": 0, "unsupported": 0}
    try:
        parsed = extract_json_from_text(raw, strict=True)
    except ParseError:
        try:
            parsed = extract_json_from_text(raw, strict=False)
        except ParseError:
            return {"claims": [], "supported": 0, "unsupported": 0}
    claims = parsed.get("claims") if isinstance(parsed, dict) else None
    if not isinstance(claims, list):
        return {"claims": [], "supported": 0, "unsupported": 0}
    verified = verify_claims([c for c in claims if isinstance(c, dict)], evidence)
    return {
        "claims": verified,
        "supported": sum(1 for c in verified if c["supported"]),
        "unsupported": sum(1 for c in verified if not c["supported"]),
    }
