"""答案自检（P3）：枚举题生成后，把「未证实/预案/风险」项移出合格清单。

动机（2026-10-18 48 题实测）：all-pass 只在 1–2 条判据的题上出现；3 条以上判据的
39 题 all-pass 全为 0。逐条失败集中在 precision 类判据——「把仅有预案/风险的 matter
当成已发生」与「并列了集合外的 matter」。检索召回不是这里的瓶颈。

本模块不读 rubric（评测金标），只做通用自检：要求答案对每个断言项给出
「已发生」的直接表述；只有风险/预案/待定的，降级到「未确认/已排除」段。

边界：开关 ANGINEER_ANSWER_AUDIT 默认 0；库白名单默认 lab-firm-full；
任何失败返回 None，原答案不变。
"""
from __future__ import annotations

import logging
import os
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_AUDIT_PROMPT = """You are auditing a draft answer to a research question.

Question:
{question}

Draft answer:
{answer}

The question asks for an exhaustive list of qualifying items. Audit the draft:

1. For every item the draft presents as qualifying/confirmed, check whether the draft
   itself states a direct positive fact that it happened (for example "issued on",
   "entered on", "confirmed on", "received on"). Mere "risk", "potential",
   "anticipated", "preparing for", "if issued", or "no second request" is NOT enough.
2. Move every such unsupported item into a section titled "Unconfirmed / excluded",
   keep one line per item explaining what is missing.
3. Keep all supported items, their citations and their text unchanged.
4. Do not invent items or citations. Do not drop anything silently.

Return the full revised answer only (markdown, same language as the draft).
"""


def enabled() -> bool:
    return os.getenv("ANGINEER_ANSWER_AUDIT", "0").strip().lower() in ("1", "true", "yes", "on")


def library_allowed(library_id: str) -> bool:
    raw = os.getenv("ANGINEER_ANSWER_AUDIT_LIBRARIES", "lab-firm-full").strip()
    if not raw or raw == "*":
        return True
    allowed = {item.strip() for item in raw.split(",") if item.strip()}
    return str(library_id or "") in allowed


def audit_answer(
    llm: Any,
    *,
    question: str,
    answer: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    """一次自检调用；失败/空结果返回 None。"""
    from ai_inference.llm_client import chat_result_guarded

    text = (answer or "").strip()
    if len(text) < 200 or len(text) > 60_000:
        return None
    messages = [
        {"role": "user", "content": _AUDIT_PROMPT.format(question=str(question)[:2000], answer=text)}
    ]
    try:
        result = chat_result_guarded(llm, messages, mode=mode, config_name=config_name, temperature=0.0)
        revised = (result.text or "").strip()
    except Exception as exc:  # noqa: BLE001 —— 自检失败不改答案
        logger.warning("answer_audit 调用失败: %s", exc)
        return None
    if len(revised) < 120 or revised == text:
        return None
    return revised


def make_audit_guard(
    base_guard: Optional[Callable],
    *,
    llm: Any,
    question: str,
    enabled_for_query: bool,
    config_name: Optional[str] = None,
    mode: str = "instruct",
):
    """包一层 final_answer_guard：先跑原 guard，再对最终答案做一次自检。"""

    def guard(added_messages):
        base = base_guard(added_messages) if base_guard else None
        if not enabled_for_query:
            return base
        final = next(
            (
                m
                for m in reversed(added_messages)
                if getattr(m, "role", "") == "assistant"
                and not getattr(m, "tool_calls", None)
                and (getattr(m, "content", "") or "").strip()
            ),
            None,
        )
        if final is None:
            return base
        current = base[0] if base and base[0] is not None else final.content
        if not current:
            return base
        revised = audit_answer(llm, question=question, answer=current, config_name=config_name, mode=mode)
        if not revised:
            return base
        note = "答案自检：未证实/预案项已移出合格清单"
        return (revised, note, "answer_audited")

    return guard
