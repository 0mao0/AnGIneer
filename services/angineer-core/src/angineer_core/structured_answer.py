"""枚举题结构化生成（P5）：模型只产出「断言 | 文档 | 引文」行，代码校验并渲染答案。

动机（2026-10-22 P4b 实测）：代码预读解决了读页覆盖与闭集精度（unbacked≈0），
剩余缺口是长枚举题的逐条覆盖与答案形态。P2.2 已证明提示词契约会被模型无视，
故本臂改为「一次结构化 LLM 调用 + 确定性校验 + 代码渲染」：引文必须在预读摘录里
逐字存在，未通过的行走 Not qualified；最终答案由渲染器拼装，不由模型自由发挥。

边界：开关 ANGINEER_ANSWER_STRUCT 默认 0；只在枚举预读注入发生的请求上生效；
解析/校验失败或无有效行时返回原答案（不允许成为新的失败点）。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

_MATTER_RE = re.compile(r"\b\d{4}-\d{5}\b")
_CLOSED_SET_RE = re.compile(r"CLOSED SET[^:]*:\s*(.+)")
_HEADER_RE = re.compile(r"^###\s*(\d{4}-\d{5})\s*\|\s*(.+)$", re.M)

_STRUCT_PROMPT = """You are extracting a structured list of qualifying matters from pre-read evidence.

Question:
{question}

Allowed matters (closed set; never output any other matter):
{closed_set}

Pre-read evidence (each block starts with "### matter_id | document title", followed by the excerpt):
{evidence}

Output format: one record per line, nothing else. Fields are separated by " || ".
Q || matter_id || document title || verbatim quote || one-sentence finding
N || matter_id || one-sentence reason

Rules:
- A matter qualifies ONLY if its excerpt states the qualifying condition asked by the question.
- The qualifying quote must describe THIS MATTER'S OWN facts (its transaction, filing, role or
  outcome), naming the client or the deal. Generic advice about the topic, strategy memos,
  templates or "how to respond" text do NOT qualify a matter.
- Each quote must be a verbatim substring of that matter's excerpt (20-400 characters).
  Add one Q line per quote when a matter has several supporting quotes.
- "document" must be the title shown in that matter's header.
- Never use " || " inside a field; replace line breaks inside a quote with a space.
- Matters without supporting evidence get one N line.
- No JSON, no code fences, no commentary."""


def enabled() -> bool:
    return os.getenv("ANGINEER_ANSWER_STRUCT", "0").strip().lower() in ("1", "true", "yes", "on")


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _loose(text: str) -> str:
    """宽松比对：只保留字母/数字/汉字并小写，抹平弯引号、标点与连字符差异。"""
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(text or "").lower())


def closed_set_from_context(context: str) -> List[str]:
    match = _CLOSED_SET_RE.search(str(context or ""))
    if not match:
        return []
    return sorted(set(_MATTER_RE.findall(match.group(1))))


def evidence_blocks(context: str) -> Dict[str, Dict[str, str]]:
    """从预读注入文本切出每个 matter 的 {title, text}。"""
    blocks: Dict[str, Dict[str, str]] = {}
    matches = list(_HEADER_RE.finditer(str(context or "")))
    for index, match in enumerate(matches):
        matter_id = match.group(1)
        title = match.group(2).strip()
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(context)
        text = str(context)[start:end]
        # 去掉尾部规则行（先切再归一，避免换行被压平后切不到）
        text = re.split(r"CLOSED SET|For each matter", text)[0]
        text = _norm(text)
        if matter_id and text:
            blocks[matter_id] = {"title": title, "text": text}
    return blocks


_RECORD_RE = re.compile(r"^\s*([QN])\s*\|")


def parse_lines(text: str) -> Optional[Dict[str, Any]]:
    """行格式：Q | matter | document | quote | finding / N | matter | reason。

    分隔符容忍单竖线与双竖线（模型实测会混用）；连续竖线视为一个。
    """
    qualifying: List[Dict[str, str]] = []
    not_qualified: List[Dict[str, str]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        match = _RECORD_RE.match(line)
        if not match:
            continue
        kind = match.group(1)
        parts = [p.strip() for p in re.split(r"\s*\|+\s*", line[match.end():])]
        parts = [p for p in parts if p]
        if kind == "Q" and len(parts) >= 3 and parts[0]:
            qualifying.append({
                "matter_id": parts[0], "document": parts[1],
                "quotes": [parts[2]], "finding": parts[3] if len(parts) > 3 else "",
            })
        elif kind == "N" and len(parts) >= 2 and parts[0]:
            not_qualified.append({"matter_id": parts[0], "reason": parts[1]})
    if not qualifying and not not_qualified:
        return None
    return {"qualifying": qualifying, "not_qualified": not_qualified}


def parse_structured(text: str) -> Optional[Dict[str, Any]]:
    raw = str(text or "").strip()
    if not raw:
        return None
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.S).strip()
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001
        return None
    return data if isinstance(data, dict) else None


def validate_rows(
    data: Dict[str, Any], blocks: Dict[str, Dict[str, str]], closed_set: List[str]
) -> Dict[str, List[Dict[str, Any]]]:
    allowed = set(closed_set) or set(blocks)
    merged: Dict[str, Dict[str, Any]] = {}
    rejected: List[Dict[str, str]] = []
    for row in data.get("qualifying") or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("matter_id") or "").strip()
        block = blocks.get(mid)
        if mid not in allowed or not block:
            rejected.append({"matter_id": mid, "reason": "不在预读允许集"})
            continue
        raw_quotes = row.get("quotes")
        if not isinstance(raw_quotes, list):
            raw_quotes = [row.get("quote")] if row.get("quote") else []
        valid: List[str] = []
        for raw in raw_quotes:
            quote = _norm(raw or "")
            loose_quote = _loose(quote)
            if len(loose_quote) < 15:
                rejected.append({"matter_id": mid, "reason": "引文过短"})
                continue
            if loose_quote not in _loose(block["text"]):
                rejected.append({"matter_id": mid, "reason": "引文不在预读摘录中"})
                continue
            if quote not in valid:
                valid.append(quote)
        if not valid:
            continue
        document = str(row.get("document") or "").strip() or block["title"]
        finding = str(row.get("finding") or "").strip()[:300]
        item = merged.setdefault(
            mid, {"matter_id": mid, "documents": [], "quotes": [], "finding": ""}
        )
        if document and document not in item["documents"]:
            item["documents"].append(document)
        for quote in valid:
            if quote not in item["quotes"]:
                item["quotes"].append(quote)
        if finding and not item["finding"]:
            item["finding"] = finding
    not_qualified: List[Dict[str, str]] = []
    for row in data.get("not_qualified") or []:
        if not isinstance(row, dict):
            continue
        mid = str(row.get("matter_id") or "").strip()
        if mid and mid in allowed and mid not in merged:
            not_qualified.append({"matter_id": mid, "reason": str(row.get("reason") or "").strip()})
    return {"qualifying": list(merged.values()), "rejected": rejected, "not_qualified": not_qualified}


def render_answer(result: Dict[str, List[Dict[str, str]]]) -> str:
    qualifying = result.get("qualifying") or []
    not_qualified = result.get("not_qualified") or []
    if not qualifying and not not_qualified:
        return ""
    lines: List[str] = ["## Qualifying matters"]
    if qualifying:
        for row in qualifying:
            docs = row.get("documents") or ([row["document"]] if row.get("document") else [])
            heading = f"### {row['matter_id']}"
            if docs:
                heading += " — " + "; ".join(docs)
            lines.append(heading)
            if row.get("finding"):
                lines.append(f"**Finding:** {row['finding']}")
            quotes = row.get("quotes") or ([row["quote"]] if row.get("quote") else [])
            for quote in quotes:
                lines.append(f"> {quote}")
    else:
        lines.append("No matter met the qualifying condition in the read evidence.")
    if not_qualified:
        lines.append("")
        lines.append("## Not qualified")
        for row in not_qualified:
            reason = f" — {row['reason']}" if row.get("reason") else ""
            lines.append(f"- {row['matter_id']}{reason}")
    return "\n".join(lines)


def structured_answer(
    llm: Any,
    *,
    question: str,
    context: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    from ai_inference.llm_client import chat_result_guarded

    blocks = evidence_blocks(context)
    closed_set = closed_set_from_context(context)
    logger.info("structured_answer enter: context=%d blocks=%d closed=%d",
                len(str(context)), len(blocks), len(closed_set))
    if not blocks or not closed_set:
        logger.warning("structured_answer 早退：blocks=%d closed=%d", len(blocks), len(closed_set))
        return None
    evidence_text = context
    max_chars = 100_000
    if len(evidence_text) > max_chars:
        evidence_text = evidence_text[:max_chars]
    messages = [{
        "role": "user",
        "content": _STRUCT_PROMPT.format(
            question=str(question)[:2000],
            closed_set=", ".join(closed_set),
            evidence=evidence_text,
        ),
    }]
    try:
        result = chat_result_guarded(llm, messages, mode=mode, config_name=config_name, temperature=0.0, max_tokens=8000)
        raw_text = result.text or ""
        data = parse_structured(raw_text) or parse_lines(raw_text)
    except Exception as exc:  # noqa: BLE001 —— 结构化失败保留原答案
        logger.warning("structured_answer 调用失败: %s", exc)
        return None
    if not data:
        try:
            import time as _time
            dump = f"D:/AI/AnGIneer/data/scratch/struct_raw_{_time.strftime('%H%M%S')}.txt"
            open(dump, "w", encoding="utf-8").write(raw_text)
        except Exception:  # noqa: BLE001
            dump = "?"
        logger.warning("structured_answer 解析失败：raw=%d 字 tail=%r dump=%s",
                       len(raw_text), raw_text[-200:], dump)
        return None
    validated = validate_rows(data, blocks, closed_set)
    if not validated["qualifying"] and validated["rejected"]:
        from collections import Counter
        reasons = Counter(r.get("reason") for r in validated["rejected"])
        logger.warning("structured_answer 全部拒绝：%s", dict(reasons))
        try:
            import time as _time
            dump = f"D:/AI/AnGIneer/data/scratch/struct_raw_{_time.strftime('%H%M%S')}.txt"
            open(dump, "w", encoding="utf-8").write(raw_text)
            logger.warning("raw dump: %s", dump)
        except Exception:  # noqa: BLE001
            pass
    rendered = render_answer(validated)
    logger.info(
        "structured_answer: qualifying=%d rejected=%d not_qualified=%d chars=%d",
        len(validated["qualifying"]), len(validated["rejected"]), len(validated["not_qualified"]), len(rendered),
    )
    return rendered or None


def make_struct_guard(
    base_guard: Optional[Callable],
    *,
    llm: Any,
    question: str,
    enabled_for_query: bool,
    evidence_context: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
):
    """包一层 final_answer_guard：枚举预读题改用结构化生成 + 代码渲染。"""

    def guard(added_messages: List[Any]):
        base = base_guard(added_messages) if base_guard else None
        if not enabled_for_query or not enabled():
            return base
        rendered = structured_answer(
            llm,
            question=question,
            context=evidence_context,
            config_name=config_name,
            mode=mode,
        )
        if not rendered:
            return base
        note = "结构化生成：断言经引文校验后由渲染器成文"
        return (rendered, note, "answer_structured")

    return guard
