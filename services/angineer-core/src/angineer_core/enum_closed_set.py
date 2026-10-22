"""枚举题闭集约束（P4）：只许断言 doc_read 实际读过的 matter。

动机（2026-10-22 注入 A/B 实测）：枚举注入把召回拉起来了（正向判据 +4.3pp），
但模型顺带断言了大量候选集里并不合格的 matter（负向判据 −10.8pp）；合取评分下
all-pass 反而从 6 降到 3。候选卡本身不是闭集——001 题 4 个「不许断言」的 matter
全在 67 个候选里，所以闭集必须由「真正读过正文的文档」定义，而不是检索列表。

边界：开关 ANGINEER_ENUM_CLOSED_SET 默认 0；只在枚举注入发生的请求上生效；
任何失败/空结果返回原答案（不允许成为新的失败点）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

_MATTER_RE = re.compile(r"\b\d{4}-\d{5}\b")
_CLOSED_SET_RE = re.compile(r"CLOSED SET[^:]*:\s*(.+)")

_REWRITE_PROMPT = """You are enforcing a closed set on a research answer.

Question:
{question}

The system read these matters from source documents (supported set):
{supported}

The draft answer also asserts these matters, but they were never read from a source document:
{unbacked}

Rewrite the draft so that:
1. Matters in the supported set keep their current statements and citations unchanged.
2. Every statement presenting an unbacked matter as qualifying/confirmed is moved to a short
   section titled "Not found in read evidence", one line per matter, saying it was not verified.
3. Do not invent matters, documents or citations. Do not delete supported content.
4. Keep the same language, structure and markdown as the draft.

Return the full revised answer only.
"""


def enabled() -> bool:
    return os.getenv("ANGINEER_ENUM_CLOSED_SET", "0").strip().lower() in ("1", "true", "yes", "on")


def collect_read_matters(messages: List[Any]) -> Set[str]:
    """工具消息里 doc_read 成功读过的 matter_id 集合（解析失败回落正则）。"""
    found: Set[str] = set()
    for message in messages or []:
        if str(getattr(message, "role", "") or "") != "tool":
            continue
        if str(getattr(message, "name", "") or "") != "doc_read":
            continue
        if bool(getattr(message, "is_error", False)):
            continue
        content = str(getattr(message, "content", "") or "")
        if not content.strip():
            continue
        try:
            data = json.loads(content)
        except Exception:  # noqa: BLE001 —— 非 JSON 回落正则
            found.update(_MATTER_RE.findall(content))
            continue
        docs = data.get("docs") if isinstance(data, dict) else None
        if isinstance(docs, list):
            for doc in docs:
                if not isinstance(doc, dict):
                    continue
                matter_id = str(doc.get("matter_id") or "").strip()
                if matter_id:
                    found.add(matter_id)
            continue
        found.update(_MATTER_RE.findall(content))
    return found


def asserted_matters(answer: str) -> Set[str]:
    return set(_MATTER_RE.findall(str(answer or "")))


def allowed_from_context(context: str) -> Set[str]:
    """从预读注入文本的 CLOSED SET 行取允许集合（代码预读臂）。"""
    match = _CLOSED_SET_RE.search(str(context or ""))
    if not match:
        return set()
    return set(_MATTER_RE.findall(match.group(1)))


def unbacked_matters(answer: str, read_matters: Set[str]) -> List[str]:
    return sorted(asserted_matters(answer) - set(read_matters or ()))


def rewrite_answer(
    llm: Any,
    *,
    question: str,
    answer: str,
    supported: Set[str],
    unbacked: List[str],
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    """一次闭集改写调用；失败/空结果返回 None。"""
    from ai_inference.llm_client import chat_result_guarded

    text = (answer or "").strip()
    if len(text) < 120 or len(text) > 60_000:
        return None
    messages = [{
        "role": "user",
        "content": _REWRITE_PROMPT.format(
            question=str(question)[:2000],
            supported=", ".join(sorted(supported)) or "(none)",
            unbacked=", ".join(unbacked),
        ) + "\n\nDraft answer:\n" + text,
    }]
    try:
        result = chat_result_guarded(llm, messages, mode=mode, config_name=config_name, temperature=0.0)
        revised = (result.text or "").strip()
    except Exception as exc:  # noqa: BLE001 —— 改写失败保留原答案
        logger.warning("enum_closed_set 改写失败: %s", exc)
        return None
    if len(revised) < 80 or revised == text:
        return None
    return revised


def make_closed_set_guard(
    base_guard: Optional[Callable],
    *,
    llm: Any,
    question: str,
    enabled_for_query: bool,
    closed_set_context: str = "",
    config_name: Optional[str] = None,
    mode: str = "instruct",
):
    """包一层 final_answer_guard：先跑原 guard，再按闭集校验/改写最终答案。"""

    def guard(added_messages: List[Any]):
        base = base_guard(added_messages) if base_guard else None
        if not enabled_for_query or not enabled():
            return base
        final = next(
            (
                m
                for m in reversed(added_messages or [])
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
        read = collect_read_matters(added_messages) | allowed_from_context(closed_set_context)
        bad = unbacked_matters(current, read)
        logger.info(
            "enum_closed_set: read=%d asserted=%d unbacked=%d %s",
            len(read), len(asserted_matters(current)), len(bad), ",".join(bad[:10]),
        )
        if not bad:
            return base
        revised = rewrite_answer(
            llm,
            question=question,
            answer=current,
            supported=read,
            unbacked=bad,
            config_name=config_name,
            mode=mode,
        )
        if not revised:
            return base
        note = f"闭集约束：{len(bad)} 个未读证据支撑的 matter 已移入未确认段"
        return (revised, note, "enum_closed_set")

    return guard
