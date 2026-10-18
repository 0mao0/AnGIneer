"""答案退化检测与单次重试（P0）。

100 题实测里 8 题退化，分三类：
- 回显题面（001/088/095）：答案逐字重复用户问题，长度 480–523；
- 空答/超短（021/080 60 字符）：证据闸拒答模板；
- 拒答模板带追问（055/059/067 90 字符）：同一段 + 一句追问。

前两类是明确的失败（没在作答）；第三类要区分「真没证据」与「有证据却拒答」——
只有 run 里出现过非空工具结果时才重试，避免对合理拒答做无谓重跑。

开关 ANGINEER_ANSWER_RETRY 默认 **0**（2026-10-18 十题门槛：重试未转化 001/080，
且整体 criterion 14.8%→13.6%，无收益；保留为可选实验，默认关闭）。
"""
from __future__ import annotations

import os
from typing import Any, List, Optional

REFUSAL_PREFIX = "没有检索到足够证据"
RETRY_HINT = (
    "上一轮回答无效（复述了问题或未给出答案）。请直接基于已检索到的证据作答，"
    "不要复述问题；逐项列出你确认的 matter/文档与依据。"
    "如果确实缺少证据，列出缺哪一项，不要用整段拒答代替。"
)


def retry_enabled() -> bool:
    return os.getenv("ANGINEER_ANSWER_RETRY", "0").strip().lower() in ("1", "true", "yes", "on")


def _has_tool_evidence(messages: List[Any]) -> bool:
    """run 内是否出现过非空工具结果（用于判断「有证据却拒答」）。"""
    for m in messages:
        if getattr(m, "role", "") != "tool":
            continue
        content = str(getattr(m, "content", "") or "")
        if not content.strip():
            continue
        if '"error"' in content[:400] or content.strip() in ("{}", "[]"):
            continue
        if '"items": []' in content or '"docs": []' in content:
            continue
        return True
    return False


def is_degenerate(answer: str, query: str, messages: Optional[List[Any]] = None) -> bool:
    text = (answer or "").strip()
    query_text = (query or "").strip()
    # 拒答模板优先判定：60/90 字符的拒答不能被「短答案」规则误判成空答；
    # 只有 run 里确实拿到过工具结果时才认为「该答未答」。
    if text.startswith(REFUSAL_PREFIX):
        return bool(messages) and _has_tool_evidence(messages)
    if len(text) < 60:
        return True
    # 回显题面：答案以问题开头（取前 60 字比较，避开标点差异）
    if query_text and text[:60] == query_text[:60]:
        return True
    if "Respond in English. Produce your complete answer" in text[:600]:
        return True
    return False


def last_assistant_text(messages: List[Any]) -> str:
    for m in reversed(messages):
        if getattr(m, "role", "") == "assistant" and not getattr(m, "tool_calls", None):
            return str(getattr(m, "content", "") or "")
    return ""
