"""聚合题结构化归类（S2，plan-ls-routing §4.2/§5.1 P0）：模型只对候选 matter 逐个归类，
代码做确定性计数与聚合表渲染——「代码从候选全集统计，模型只做归类；明细与计数对账」。

三段式：
  候选全集（复用 enum 预读注入，运行时信号，金标零接触）
  → guard 内第二次 LLM 调用产归类行（C/N 行协议，无数字）
  → 代码校验（闭集+引文在场+维度合法）→ 分类完备性兜底（未归类进 fallback 桶，
    不许归类缺失）→ 维度计数矩阵/份额 → markdown 聚合表 + 支撑明细 + 对账段
    + 召回缺口标注（候选全集≠金标全集，主线①口径）。

维度规格来自预注册 experiment config（ANGINEER_ANSWER_AGGREGATE_SPECS 指向 JSON），
按题面子串匹配（match）；无匹配 spec＝本臂不生效（回退 S1/自由文本路径，生产行为不变）。
安全终态优先（§4.5）：base guard 已是 no_evidence 终态时不覆盖。

开关：ANGINEER_ANSWER_AGGREGATE 默认 0；只在枚举预读注入发生的请求上生效。
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from angineer_core.structured_answer import (
    SAFE_TERMINAL_CODES,
    _index_doc_id,
    _row_citation,
    closed_set_from_context,
    evidence_blocks,
    split_preread_index,
)

logger = logging.getLogger(__name__)

_MATTER_RE = re.compile(r"\b\d{4}-\d{5}\b")
_SPEC_CACHE: Dict[str, Optional[Dict[str, Any]]] = {}

# 安全终态清单与判断、预读索引解析共享自 structured_answer（P0b ⑤/③）
_SAFE_TERMINAL_CODES = SAFE_TERMINAL_CODES
_split_preread_index = split_preread_index
_index_doc_id = _index_doc_id

# 二次加深（归类失败信号）：单次重归类调用的字符预算与 matter 批上限
_DEEPEN_CHARS = 4000
_DEEPEN_CALL_BUDGET = 60_000
_DEEPEN_BATCH_MAX = 12


def enabled() -> bool:
    return os.getenv("ANGINEER_ANSWER_AGGREGATE", "0").strip().lower() in ("1", "true", "yes", "on")


_AGG_QUERY_RE = re.compile(
    r"how (?:many|often|much)|what share|what percentage|percentage of|"
    r"break(?:\s|-)?down|track how|share of",
    re.I,
)


def is_aggregation(query: str) -> bool:
    """聚合题判定（宁严勿宽）：计数/占比/分布类问法。"""
    return bool(_AGG_QUERY_RE.search(str(query or "")))


def load_spec(question: str) -> Optional[Dict[str, Any]]:
    """按题面子串匹配预注册维度规格；无匹配/文件不可用返回 None（本臂不生效）。"""
    path = os.getenv("ANGINEER_ANSWER_AGGREGATE_SPECS", "").strip()
    if not path:
        return None
    if path not in _SPEC_CACHE:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            _SPEC_CACHE[path] = data if isinstance(data, dict) else None
        except Exception as exc:  # noqa: BLE001 —— 配置不可用＝臂不生效，不阻断问答
            logger.warning("aggregate_answer 配置加载失败(%s): %s", path, exc)
            _SPEC_CACHE[path] = None
    data = _SPEC_CACHE[path]
    for spec in (data or {}).get("specs") or []:
        if not isinstance(spec, dict):
            continue
        match = str(spec.get("match") or "")
        if match and match.lower() in str(question or "").lower():
            return spec
    return None


def _dim_instructions(spec: Dict[str, Any]) -> str:
    lines: List[str] = []
    for index, dim in enumerate(spec.get("dims") or [], start=1):
        name = str(dim.get("name") or f"dim{index}")
        kind = str(dim.get("kind") or "enum")
        hint = str(dim.get("prompt_hint") or "")
        if kind == "enum":
            buckets = " / ".join(str(b) for b in dim.get("buckets") or [])
            lines.append(f"{index}. {name}: one of exactly [{buckets}]. {hint}".strip())
        elif kind == "free":
            pattern = str(dim.get("pattern") or "")
            extra = f" Format: {pattern}." if pattern else ""
            fallback = str(dim.get("fallback_value") or "unknown")
            lines.append(
                f"{index}. {name}: {hint}{extra} If the excerpt does not state it, use {fallback}.".strip()
            )
        else:  # entity
            extra = str(dim.get("prompt_extra") or "")
            fallback = str(dim.get("fallback_value") or "unclassified")
            lines.append(
                f"{index}. {name}: {hint} {extra} If the excerpt shows none, use {fallback}.".strip()
            )
    return "\n".join(lines)


_PROMPT_TEMPLATE = """You are classifying every candidate matter from pre-read evidence so the system can compute an aggregate table by code. You NEVER compute numbers.

Question:
{question}

Allowed matters (closed set; never output any other matter):
{closed_set}

Pre-read evidence (each block starts with "### matter_id | document title", followed by the excerpt):
{evidence}

Classification dimensions (one value per dimension, in this exact order):
{dim_instructions}

Output format: one record per line, nothing else. Fields are separated by " || ".
C || matter_id || <dim 1 value> || ... || <dim {n_dims} value> || verbatim quote || one-sentence finding
N || matter_id || one-sentence reason why this matter cannot be classified

Rules:
- Output exactly one C line per matter whose excerpt states the facts needed to classify it.
- The quote must be a verbatim substring of that matter's excerpt (20-400 characters) and must
  support the dimension values you chose. Use this matter's own facts only.
- Dimension values must follow the dimension rules above; never invent other bucket names.
- Never use " || " inside a field; replace line breaks inside a quote with a space.
- Matters whose excerpt is unreadable or insufficient get one N line (the system classifies them
  into the fallback bucket; do not guess).
- No JSON, no code fences, no commentary."""


def _norm(text: str) -> str:
    return " ".join(str(text or "").split())


def _loose(text: str) -> str:
    """与 structured_answer 同一宽松归一：小写+只留字母/数字/汉字。"""
    return re.sub(r"[^0-9a-z一-鿿]+", "", str(text or "").lower())


def _entity_key(value: str) -> str:
    """实体分组键：仅大小写折叠+空白归一；不做后缀/词形合并（保「Distinct from」）。"""
    return " ".join(str(value or "").split()).casefold()


def parse_cls_lines(text: str, n_dims: int) -> Dict[str, List[Dict[str, Any]]]:
    """C/N 行解析：C = matter + n_dims 个维度值 + quote + finding（位置固定）。

    C 行保位解析（空字段不能丢，否则维度错位）；N 行过滤空段。
    """
    classified: List[Dict[str, Any]] = []
    unclassified: List[Dict[str, Any]] = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not re.match(r"^[CN]\s*\|", line):
            continue
        parts = [p.strip() for p in re.split(r"\s*\|+\s*", line)]
        kind, fields = parts[0], parts[1:]
        if kind == "N":
            fields = [p for p in fields if p]
            if len(fields) >= 2 and fields[0]:
                unclassified.append({"matter_id": fields[0], "reason": fields[1]})
            continue
        matter = fields[0] if fields else ""
        if not matter:
            continue
        if len(fields) < n_dims + 2:
            unclassified.append({"matter_id": matter, "reason": "字段数不足（维度值缺失）"})
            continue
        values = fields[1:1 + n_dims]
        quote = fields[1 + n_dims]
        finding = " ".join(p for p in fields[2 + n_dims:] if p)
        classified.append({"matter_id": matter, "values": values, "quote": quote, "finding": finding})
    return {"classified": classified, "unclassified": unclassified}


def _validate_value(dim: Dict[str, Any], raw: str) -> Tuple[Optional[str], str]:
    """单维度值校验；返回 (规范化值|None, 失败原因)。"""
    kind = str(dim.get("kind") or "enum")
    value = _norm(raw)
    if not value:
        return None, "维度值缺失"
    if kind == "enum":
        buckets = [str(b) for b in dim.get("buckets") or []]
        folded = value.casefold().replace("-", "_").replace(" ", "_")
        for bucket in buckets:
            if folded == bucket.casefold():
                return bucket, ""
        return None, f"维度值不在桶清单: {value}"
    if kind == "free":
        pattern = dim.get("pattern")
        if pattern and not re.match(pattern, value):
            return None, f"维度值不合格式: {value}"
        return value, ""
    # entity：大小写/空白归一入库，展示名取首见原串
    return _entity_key(value), ""


def classify(
    spec: Dict[str, Any],
    parsed: Dict[str, List[Dict[str, Any]]],
    blocks: Dict[str, Dict[str, str]],
    closed_set: List[str],
) -> Dict[str, Any]:
    """逐行校验 + 分类完备性兜底：候选全集内每个 matter 必须恰有一个归类。"""
    dims = spec.get("dims") or []
    fallbacks = [str(d.get("fallback_value") or ("unknown" if str(d.get("kind")) != "entity" else "unclassified"))
                 for d in dims]
    allowed = set(closed_set) or set(blocks)
    classifications: Dict[str, Dict[str, Any]] = {}
    rejected: List[Dict[str, str]] = []

    def _backstop(mid: str, reason: str) -> None:
        if mid in classifications:
            return
        display_reason = reason
        row: Dict[str, Any] = {
            "matter_id": mid,
            "values": list(fallbacks),
            "quote": "",
            "finding": "",
            "backstop": True,
            "reason": display_reason,
            "document": blocks.get(mid, {}).get("title", ""),
        }
        classifications[mid] = row

    for row in parsed.get("classified") or []:
        mid = str(row.get("matter_id") or "").strip()
        block = blocks.get(mid)
        if mid not in allowed or not block:
            rejected.append({"matter_id": mid, "reason": "不在预读允许集"})
            continue
        quote = _norm(row.get("quote") or "")
        loose_quote = _loose(quote)
        if len(loose_quote) < 15:
            rejected.append({"matter_id": mid, "reason": "引文过短"})
            continue
        if loose_quote not in _loose(block["text"]):
            rejected.append({"matter_id": mid, "reason": "引文不在预读摘录中"})
            continue
        values: List[Any] = []
        ok = True
        for dim, raw in zip(dims, row.get("values") or []):
            value, err = _validate_value(dim, raw)
            if value is None:
                rejected.append({"matter_id": mid, "reason": err})
                ok = False
                break
            values.append({"key": value, "display": _norm(raw)} if str(dim.get("kind")) == "entity" else value)
        if not ok:
            continue
        if mid in classifications:
            continue
        classifications[mid] = {
            "matter_id": mid, "values": values, "quote": quote,
            "finding": _norm(row.get("finding") or "")[:300], "backstop": False,
            "document": block["title"],
        }
    # N 行＝模型明示读不出 → 兜底
    for row in parsed.get("unclassified") or []:
        mid = str(row.get("matter_id") or "").strip()
        if mid in allowed:
            _backstop(mid, str(row.get("reason") or "模型明示不可归类"))
    # 完备性兜底：候选全集里仍无归类的 matter（含被拒行）一律进 fallback 桶
    for mid in sorted(allowed):
        if mid in blocks:
            _backstop(mid, "未归类兜底（候选全集内无有效归类行）")
    return {"classifications": classifications, "rejected": rejected}


def _display(dim: Dict[str, Any], value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("display") or value.get("key") or "")
    out = str(value or "")
    if str(dim.get("kind")) == "enum":
        return out.replace("_", "-")
    return out


def _chat(llm: Any, messages: List[Dict[str, str]], *, config_name: Optional[str], mode: str):
    """LLM 调用缝隙（测试在此打桩）；懒加载 ai_inference，避免模块导入期拉起客户端。"""
    from ai_inference.llm_client import chat_result_guarded

    return chat_result_guarded(llm, messages, mode=mode, config_name=config_name, temperature=0.0, max_tokens=8000)


def _read_docs_batch(library_id: str, doc_ids: List[str], query: str, max_chars: int) -> Dict[str, Any]:
    """读页缝隙（测试在此打桩）；懒加载 docs-core，保持包间解耦。"""
    from docs_core.step09_query.doc_search import read_documents

    return read_documents(
        library_id=library_id,
        doc_ids=doc_ids,
        query=str(query or "")[:400],
        max_chars_per_doc=max_chars,
        mode="match",
    )


def _deep_read_blocks(
    library_id: str, doc_map: Dict[str, Any], mids: List[str], query: str
) -> Dict[str, Dict[str, str]]:
    """对兜底 matter 的主代表文档按 4000 字重读（match 模式），返回 {mid: {title, text}}。

    doc_map 值兼容 {mid: doc_id}（旧索引）与 {mid: [doc1, doc2]}（v2，只取主文档）。
    深度优先是实测结论（见预注册 §6 迭代 2/3）：同一篇文档读到 4000 字有效（升级 6/9），
    换第二篇各读 2000 字反而回归（升级 1/9）——细节内容在主文档更深处，不在第二篇。
    """
    out: Dict[str, Dict[str, str]] = {}
    ids: List[Tuple[str, str]] = []
    for mid in mids:
        spec_ids = doc_map.get(mid)
        primary = spec_ids[0] if isinstance(spec_ids, list) and spec_ids else spec_ids
        if primary:
            ids.append((mid, str(primary)))
    for start in range(0, len(ids), 8):
        batch = ids[start:start + 8]
        try:
            result = _read_docs_batch(library_id, [doc_id for _, doc_id in batch], query, _DEEPEN_CHARS)
        except Exception as exc:  # noqa: BLE001 —— 加深失败降级为保持兜底
            logger.warning("aggregate_answer 加深读失败(batch %d): %s", start, exc)
            continue
        docs = {str(d.get("doc_id") or ""): d for d in result.get("docs") or []}
        for mid, doc_id in batch:
            doc = docs.get(doc_id) or {}
            text = " ".join(str(doc.get("text") or "").split())
            if text:
                out[mid] = {"title": str(doc.get("title") or ""), "text": text[:_DEEPEN_CHARS]}
    return out


def _deepen_reclassify(
    llm: Any,
    *,
    question: str,
    spec: Dict[str, Any],
    result: Dict[str, Any],
    index: Dict[str, Any],
    config_name: Optional[str],
    mode: str,
) -> int:
    """归类失败信号驱动的二次加深：只对兜底 matter 重读并重归类，成功则升级该行。

    返回升级（兜底→有效归类）的 matter 数；仍失败的保持兜底（如实），不抛错。
    """
    if not index:
        return 0
    library_id = str(index.get("library") or "")
    doc_map = index.get("doc_ids") or {}
    backstop_mids = sorted(
        mid for mid, row in result["classifications"].items() if row.get("backstop")
    )
    targets = [mid for mid in backstop_mids if doc_map.get(mid)]
    if not library_id or not targets:
        return 0
    n_dims = len(spec.get("dims") or [])
    deep_blocks_all = _deep_read_blocks(library_id, doc_map, targets, question)
    logger.info("aggregate_answer deepen: backstop=%d 重读成功=%d", len(backstop_mids), len(deep_blocks_all))
    upgraded = 0
    # 按字符预算分批（每批 ≤60k 且 ≤12 个 matter）
    batch: List[str] = []
    budget = 0
    batches: List[List[str]] = []
    for mid in targets:
        if mid not in deep_blocks_all:
            continue
        cost = len(deep_blocks_all[mid]["text"])
        if batch and (budget + cost > _DEEPEN_CALL_BUDGET or len(batch) >= _DEEPEN_BATCH_MAX):
            batches.append(batch)
            batch, budget = [], 0
        batch.append(mid)
        budget += cost
    if batch:
        batches.append(batch)
    for batch_mids in batches:
        blocks2 = {mid: deep_blocks_all[mid] for mid in batch_mids}
        lines = [
            "## Deep re-read evidence (system, deterministic)",
            "These are LONGER excerpts of matters that could not be classified from the first excerpt.",
        ]
        for mid in batch_mids:
            lines.append(f"\n### {mid} | {blocks2[mid]['title']}\n{blocks2[mid]['text']}")
        lines.append("\nCLOSED SET (only these matters may be asserted as qualifying): " + ", ".join(batch_mids))
        lines.append(
            "For each matter, classify it only if the longer excerpt states the facts needed; "
            "otherwise it stays unclassified."
        )
        messages = [{
            "role": "user",
            "content": _PROMPT_TEMPLATE.format(
                question=str(question)[:2000],
                closed_set=", ".join(batch_mids),
                evidence="\n".join(lines),
                dim_instructions=_dim_instructions(spec),
                n_dims=n_dims,
            ),
        }]
        try:
            call = _chat(llm, messages, config_name=config_name, mode=mode)
            parsed2 = parse_cls_lines(call.text or "", n_dims)
        except Exception as exc:  # noqa: BLE001 —— 重归类失败保持兜底
            logger.warning("aggregate_answer 重归类调用失败: %s", exc)
            continue
        result2 = classify(spec, parsed2, blocks2, batch_mids)
        for mid in batch_mids:
            new_row = result2["classifications"].get(mid)
            if new_row and not new_row.get("backstop"):
                result["classifications"][mid] = new_row
                upgraded += 1
            elif mid in result["classifications"]:
                result["classifications"][mid]["reason"] = "加深重读后仍不可归类"
    return upgraded


def compute_aggregate(spec: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
    """确定性计数：维度分组 + 份额 + 对账。纯函数，无 LLM。"""
    dims = spec.get("dims") or []
    classifications: Dict[str, Dict[str, Any]] = result.get("classifications") or {}
    excluded_spec = spec.get("population_exclude") or {}
    exclude_dim = excluded_spec.get("dim")
    exclude_value = excluded_spec.get("value")

    def _row_dim(row: Dict[str, Any], name: str) -> Tuple[Optional[Dict[str, Any]], Any]:
        for dim, value in zip(dims, row.get("values") or []):
            if str(dim.get("name")) == name:
                return dim, value
        return None, None

    def _dim_key(dim: Optional[Dict[str, Any]], value: Any) -> str:
        if isinstance(value, dict):
            return str(value.get("key") or "")
        return _entity_key(str(value)) if dim and str(dim.get("kind")) == "entity" else str(value)

    population: List[Dict[str, Any]] = []
    excluded: List[Dict[str, Any]] = []
    for mid in sorted(classifications):
        row = classifications[mid]
        if exclude_dim and exclude_value is not None:
            _dim, value = _row_dim(row, str(exclude_dim))
            if _dim_key(_dim, value) == str(exclude_value):
                excluded.append(row)
                continue
        population.append(row)

    group_by = spec.get("group_by") or [str(d.get("name")) for d in dims]
    group_dim_names = [str(g) for g in group_by]
    groups: Dict[Tuple[str, ...], Dict[str, int]] = {}
    group_displays: Dict[Tuple[str, ...], Dict[str, str]] = {}
    for row in population:
        keys: List[str] = []
        displays: Dict[str, str] = {}
        for name in group_dim_names:
            dim, value = _row_dim(row, name)
            keys.append(_dim_key(dim, value))
            displays[name] = _display(dim, value)
        key_tuple = tuple(keys)
        groups.setdefault(key_tuple, {"count": 0})
        groups[key_tuple]["count"] += 1
        group_displays.setdefault(key_tuple, displays)

    share = spec.get("share") or None
    share_rows: List[Dict[str, Any]] = []
    if share:
        num_dim = str(share.get("numerator_dim"))
        num_value = share.get("numerator_value")
        denom_excl = [
            (str(x.get("dim")), x.get("value")) for x in (share.get("denominator_exclude") or [])
            if isinstance(x, dict)
        ]

        def _denominator_excluded(row: Dict[str, Any]) -> bool:
            for d, v in denom_excl:
                _dim, value = _row_dim(row, d)
                if _dim_key(_dim, value) == str(v):
                    return True
            return False

        def _group_keys(row: Dict[str, Any]) -> Tuple[str, ...]:
            keys: List[str] = []
            for name in group_dim_names:
                dim, value = _row_dim(row, name)
                keys.append(_dim_key(dim, value))
            return tuple(keys)

        by_group: Dict[Tuple[str, ...], Dict[str, int]] = {}
        for row in population:
            if _denominator_excluded(row):
                continue
            bucket = by_group.setdefault(_group_keys(row), {"num": 0, "den": 0})
            bucket["den"] += 1
            _dim, value = _row_dim(row, num_dim)
            if _dim_key(_dim, value) == str(num_value):
                bucket["num"] += 1
        for keys, bucket in by_group.items():
            num, den = bucket["num"], bucket["den"]
            frac = (num / den) if den else 0.0
            share_rows.append({
                "group": group_displays.get(keys, {}),
                "num": num, "den": den,
                "share": f"{num}/{den} ({round(frac * 100)}%)",
            })
        share_rows.sort(key=lambda r: tuple(str(v) for v in r["group"].values()))

    table_rows = [
        {"group": group_displays[keys], "count": bucket["count"]}
        for keys, bucket in sorted(
            groups.items(),
            key=lambda kv: (-kv[1]["count"], tuple(str(x) for x in kv[0])),
        )
    ]
    reconciliation = {
        "candidates_n": len(classifications),
        "population_n": len(population),
        "excluded_n": len(excluded),
        "classified_n": sum(1 for r in classifications.values() if not r.get("backstop")),
        "backstop_n": sum(1 for r in classifications.values() if r.get("backstop")),
        "complete": len(population) + len(excluded) == len(classifications),
        "counts_sum_matches": sum(b["count"] for b in groups.values()) == len(population),
    }
    return {
        "table_rows": table_rows,
        "share_rows": share_rows,
        "excluded": excluded,
        "reconciliation": reconciliation,
    }


def render_answer(
    spec: Dict[str, Any], result: Dict[str, Any], aggregate: Dict[str, Any],
    cites: Optional[Dict[str, str]] = None,
) -> str:
    dims = spec.get("dims") or []
    group_by = spec.get("group_by") or [str(d.get("name")) for d in dims]
    group_names = [str(g) for g in group_by]
    rec = aggregate.get("reconciliation") or {}
    lines: List[str] = ["## Aggregate result (code-computed from the candidate set; the model only classifies)"]

    if aggregate.get("share_rows"):
        header = "| " + " | ".join(group_names) + " | share (numerator/population) |"
        lines += [header, "|" + "---|" * (len(group_names) + 1)]
        for row in aggregate["share_rows"]:
            cells = [row["group"].get(n, "") for n in group_names] + [row["share"]]
            lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    if aggregate.get("table_rows"):
        lines.append("")
        lines.append("### Counts by " + " × ".join(group_names))
        header = "| " + " | ".join(group_names) + " | matters |"
        lines += [header, "|" + "---|" * (len(group_names) + 1)]
        for row in aggregate["table_rows"]:
            cells = [row["group"].get(n, "") for n in group_names] + [str(row["count"])]
            lines.append("| " + " | ".join(str(c) for c in cells) + " |")

    if aggregate.get("excluded"):
        lines.append("")
        lines.append(f"### Excluded from population ({len(aggregate['excluded'])})")
        for row in aggregate["excluded"]:
            reason = f" — {row.get('reason')}" if row.get("reason") else ""
            lines.append(f"- {row['matter_id']}{reason}")

    lines.append("")
    lines.append("### Supporting detail (one row per candidate matter)")
    classifications: Dict[str, Dict[str, Any]] = result.get("classifications") or {}
    for mid in sorted(classifications):
        row = classifications[mid]
        dim_txt = " | ".join(_display(d, v) for d, v in zip(dims, row.get("values") or []))
        tag = "（兜底归类）" if row.get("backstop") else ""
        marker = (cites or {}).get(mid) if not row.get("backstop") else None
        marker_txt = f" [{marker}]" if marker else ""
        lines.append(f"- {row['matter_id']} | {dim_txt}{marker_txt}{tag} — {row.get('finding') or ''}".rstrip(" —"))
        if row.get("quote"):
            lines.append(f"  > {row['quote']}")
        if row.get("reason"):
            lines.append(f"  > reason: {row['reason']}")

    lines.append("")
    lines.append("### Reconciliation")
    lines.append(
        f"- candidates={rec.get('candidates_n')} population={rec.get('population_n')} "
        f"excluded={rec.get('excluded_n')} classified={rec.get('classified_n')} "
        f"backstop={rec.get('backstop_n')}"
    )
    lines.append(f"- classification complete: {'yes' if rec.get('complete') else 'NO'}")
    lines.append(f"- counts sum == population rows: {'yes' if rec.get('counts_sum_matches') else 'NO'}")
    lines.append(
        "- Note: totals are computed over the retrieval candidate set only; matters missed by "
        "retrieval are NOT in this table (candidate set ≠ gold population). See the recall audit "
        "for the measured gap."
    )
    return "\n".join(lines)


def aggregate_answer(
    llm: Any,
    *,
    question: str,
    context: str,
    spec: Dict[str, Any],
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[str]:
    """兼容出口：只返回渲染文本（引用走 aggregate_answer_ex 的 citations）。"""
    result = aggregate_answer_ex(
        llm, question=question, context=context, spec=spec, config_name=config_name, mode=mode
    )
    return result[0] if result else None


def aggregate_answer_ex(
    llm: Any,
    *,
    question: str,
    context: str,
    spec: Dict[str, Any],
    config_name: Optional[str] = None,
    mode: str = "instruct",
) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    """S2 编排：归类 LLM 调用 → 校验/兜底/加深 → 计数 → 渲染，返回 (渲染文本, citations)。

    citations 由预读索引 K 号构造（P0b ③）：渲染行内 [K] 与该列表同集（§1.3 契约）。
    """
    context_clean, index = _split_preread_index(context)
    cites = (index or {}).get("cites") if isinstance(index, dict) else None
    blocks = evidence_blocks(context)
    closed_set = closed_set_from_context(context)
    logger.info("aggregate_answer enter: context=%d blocks=%d closed=%d",
                len(str(context)), len(blocks), len(closed_set))
    if not blocks or not closed_set:
        logger.warning("aggregate_answer 早退：blocks=%d closed=%d", len(blocks), len(closed_set))
        return None
    evidence_text = context_clean
    if len(evidence_text) > 100_000:
        evidence_text = evidence_text[:100_000]
    n_dims = len(spec.get("dims") or [])
    if n_dims <= 0:
        logger.warning("aggregate_answer 早退：spec 无维度")
        return None
    messages = [{
        "role": "user",
        "content": _PROMPT_TEMPLATE.format(
            question=str(question)[:2000],
            closed_set=", ".join(closed_set),
            evidence=evidence_text,
            dim_instructions=_dim_instructions(spec),
            n_dims=n_dims,
        ),
    }]
    try:
        call = _chat(llm, messages, config_name=config_name, mode=mode)
        raw_text = call.text or ""
    except Exception as exc:  # noqa: BLE001 —— 归类失败保留原答案
        logger.warning("aggregate_answer 调用失败: %s", exc)
        return None
    parsed = parse_cls_lines(raw_text, n_dims)
    if not parsed["classified"] and not parsed["unclassified"]:
        logger.warning("aggregate_answer 解析失败：raw=%d 字 tail=%r", len(raw_text), raw_text[-200:])
        return None
    result = classify(spec, parsed, blocks, closed_set)
    # S2 二次加深（归类失败信号）：兜底 matter 重读 4000 字后单独重归类，成功则升级
    upgraded = 0
    if spec.get("deepen") and index:
        upgraded = _deepen_reclassify(
            llm, question=question, spec=spec, result=result, index=index,
            config_name=config_name, mode=mode,
        )
    aggregate = compute_aggregate(spec, result)
    rendered = render_answer(spec, result, aggregate, cites=cites)
    rec = aggregate["reconciliation"]
    logger.info(
        "aggregate_answer: candidates=%d classified=%d backstop=%d excluded=%d complete=%s upgraded=%d",
        rec["candidates_n"], rec["classified_n"], rec["backstop_n"], rec["excluded_n"],
        rec["complete"], upgraded,
    )
    if not rendered:
        return None
    citations: List[Dict[str, Any]] = []
    for mid, row in result.get("classifications", {}).items():
        marker = (cites or {}).get(mid)
        if not marker or row.get("backstop"):
            continue
        citations.append(_row_citation(
            mid, marker, _index_doc_id(index, mid),
            row.get("document") or "", row.get("quote") or "",
        ))
    return (rendered, citations)


def make_aggregate_guard(
    base_guard: Optional[Callable],
    *,
    llm: Any,
    question: str,
    enabled_for_query: bool,
    evidence_context: str,
    config_name: Optional[str] = None,
    mode: str = "instruct",
):
    """包一层 final_answer_guard：聚合题改用「模型归类 + 代码计数」成文。

    §4.5 安全终态优先：base 已是 no_evidence 终态时不覆盖（与 make_struct_guard 的
    缺陷不同——本守卫按正确顺序实现；struct guard 本身的修复归 P0b③）。
    """

    def guard(added_messages: List[Any]):
        base = base_guard(added_messages) if base_guard else None
        if not enabled_for_query or not enabled():
            return base
        if base is not None and len(base) == 3 and base[2] in _SAFE_TERMINAL_CODES:
            return base
        spec = load_spec(question)
        if not spec:
            return base
        outcome = aggregate_answer_ex(
            llm,
            question=question,
            context=evidence_context,
            spec=spec,
            config_name=config_name,
            mode=mode,
        )
        if not outcome:
            return base
        rendered, citations = outcome
        note = "聚合表生成：模型归类、代码从候选全集确定性计数（含对账与召回缺口标注）"
        extras = {"citations": citations} if citations else None
        if extras:
            return (rendered, note, "answer_aggregate", extras)
        return (rendered, note, "answer_aggregate")

    return guard
