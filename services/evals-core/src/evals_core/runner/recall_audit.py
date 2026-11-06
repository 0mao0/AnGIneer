"""候选集合对账（召回缺口如实报告）——plan-ls-routing.md §5 施工主线第①项。

对每道评测题，把「链路实际提供的候选集」（prediction.retrieved_items，多轮并集，
policy_query 已按 item_id 去重）与「金标」按可机读粒度对账，产出召回缺口标注。
定位是交付契约的报告件：纯离线、只读 prediction、金标只进报告不进生成/检索链路
（金标隔离天然满足）；对账故障自兜底为 audit_error，绝不影响评测 run。

口径（读报告前必看）：
- recall = 候选覆盖率：hit 表示金标标识出现在候选里，不代表答案用对了；
- 候选记录分级 candidate_record：retrieved_items（候选全集，现行 schema）>
  citations_only（旧 run 只落了 citation 分配子集，召回是**下界**，如实标注）>
  none（status="no_candidates_recorded" 单独成桶——「没记录」≠「召回 0」，不得混入分母）；
- primary 口径 = retrieved_items（候选全集）；secondary = evidences（上桌子集），
  两口径差值用于截断层归因（top_k → CONTEXT_TOP_N → 体积软帽逐层截断）；
- 金标三档粒度按可用字段自动路由：target（gold_target_ids/gold_chunk_ids）>
  doc（gold_doc_ids）> matter（rubric criteria 自由文本正则抽 matter 号，
  先例 data/scratch/harvey-lab/tools/p05_query_rewrite.py 的 MATTER_RE）；
- matter 级候选识别双源：doc_catalog 映射（权威；调用方注入 resolver，evals-core
  核心不 import docs-core）优先，fallback 对候选 title/text/content 正则（来源
  text_regex，召回是下界——块文没印 matter 号也会漏）；来源如实标注 matter_source；
- 无可机读金标 → status="no_machine_gold"，单独计数，不静默退出分母。
"""
from __future__ import annotations

import json
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# Harvey matter 号形态（与 p05_query_rewrite.py 保持同一先例）
MATTER_RE = re.compile(r"\b(\d{4}-\d{5})\b")

# missing 列表落库截断上限（85 判据题的金标可到几十个 matter，防 prediction 外字段膨胀）
_MISSING_CAP = 50

# matter_resolver：doc_id -> matter_id | None；None 表示未注入（走正则 fallback）
MatterResolver = Callable[[str], Optional[str]]


def _dedup(values: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _gold_matters(rubric_gold: Any) -> List[str]:
    """rubric criteria 自由文本里抽 matter 号（先例 p05_query_rewrite.py）。"""
    if isinstance(rubric_gold, str):
        try:
            rubric_gold = json.loads(rubric_gold)
        except Exception:  # noqa: BLE001
            return []
    if not isinstance(rubric_gold, dict):
        return []
    criteria = rubric_gold.get("criteria")
    if not isinstance(criteria, list):
        return []
    text = " ".join(
        str(c.get("text") or "") for c in criteria if isinstance(c, dict)
    )
    return sorted(set(MATTER_RE.findall(text)))


def extract_gold_units(question: Dict[str, Any]) -> Tuple[Optional[str], Optional[List[str]]]:
    """金标三档探测：target > doc > matter。无可机读金标返回 (None, None)。"""
    retrieval_gold = question.get("retrieval_gold")
    if not isinstance(retrieval_gold, dict):
        retrieval_gold = {}
    ids: List[str] = []
    for key in ("gold_target_ids", "gold_chunk_ids"):
        for x in retrieval_gold.get(key) or []:
            s = str(x or "").strip()
            if s:
                ids.append(s)
    if ids:
        return "target", _dedup(ids)
    doc_ids = [str(x or "").strip() for x in retrieval_gold.get("gold_doc_ids") or []]
    doc_ids = [x for x in doc_ids if x]
    if doc_ids:
        return "doc", _dedup(doc_ids)
    matters = _gold_matters(question.get("rubric_gold"))
    if matters:
        return "matter", matters
    return None, None


def _dedup_items(items: List[Dict[str, Any]], id_key: str) -> List[Dict[str, Any]]:
    """按 id 去重（同 id 保留首条）；无 id 的条目逐条保留。"""
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for it in items:
        key = str(it.get(id_key) or "")
        if key:
            if key in seen:
                continue
            seen.add(key)
        out.append(it)
    return out


def _candidate_target_ids(items: List[Dict[str, Any]], extra_id_keys: Tuple[str, ...]) -> set:
    """target 级候选：citation_target_id ∪ item_id（chunk 命名空间双路命中）。"""
    ids: set = set()
    for it in items:
        for key in ("citation_target_id", "item_id", *extra_id_keys):
            v = str(it.get(key) or "").strip()
            if v:
                ids.add(v)
        meta = it.get("metadata")
        if isinstance(meta, dict):
            v = str(meta.get("citation_target_id") or "").strip()
            if v:
                ids.add(v)
    return ids


def _candidate_doc_ids(items: List[Dict[str, Any]]) -> set:
    ids: set = set()
    for it in items:
        v = str(it.get("doc_id") or "").strip()
        if v:
            ids.add(v)
    return ids


def candidate_matters(
    items: List[Dict[str, Any]], resolver: Optional[MatterResolver]
) -> Tuple[set, str]:
    """候选 matter 识别双源：catalog 映射优先，正则 fallback；返回 (matters, source)。"""
    matters: set = set()
    catalog_hits = 0
    regex_hits = 0
    for it in items:
        doc_id = str(it.get("doc_id") or "").strip()
        mapped = resolver(doc_id) if (resolver is not None and doc_id) else None
        if mapped:
            matters.add(str(mapped))
            catalog_hits += 1
            continue
        text = " ".join(
            str(it.get(k) or "") for k in ("title", "text", "content")
        )
        found = set(MATTER_RE.findall(text))
        if found:
            matters |= found
            regex_hits += 1
    if catalog_hits and regex_hits:
        source = "mixed"
    elif catalog_hits:
        source = "catalog"
    elif regex_hits:
        source = "text_regex"
    else:
        source = "none"
    return matters, source


def _hit_missing(gold: List[str], cand: set) -> Tuple[int, List[str]]:
    gold_set = set(gold)
    hit = gold_set & cand
    missing = sorted(gold_set - hit)
    return len(hit), missing[:_MISSING_CAP]


def _compute_audit(
    prediction: Any, question: Dict[str, Any], matter_resolver: Optional[MatterResolver]
) -> Dict[str, Any]:
    if not isinstance(prediction, dict):
        prediction = {}
    audit: Dict[str, Any] = {
        "candidates_n": 0,
        "evidences_n": 0,
        "unit": None,
        "status": "ok",
        "gold_total": 0,
        "hit": None,
        "recall": None,
        "missing": [],
        "matter_source": None,
        "candidate_record": None,
        "secondary": None,
    }
    unit, gold = extract_gold_units(question)

    raw_items = prediction.get("retrieved_items")
    raw_cites = prediction.get("citations")
    if isinstance(raw_items, list):
        # 现行 schema：候选全集（多轮并集，key 恒在——空列表=检索真为空，如实记 0）
        items = _dedup_items([it for it in raw_items if isinstance(it, dict)], "item_id")
        audit["candidate_record"] = "retrieved_items"
    elif isinstance(raw_cites, list) and raw_cites:
        # 旧 run 只有 citation 分配子集：召回下界，如实降级标注
        items = []
        for c in raw_cites:
            if not isinstance(c, dict):
                continue
            items.append({
                "item_id": str(c.get("target_id") or ""),
                "doc_id": str(c.get("doc_id") or ""),
                "citation_target_id": str(c.get("target_id") or ""),
                "title": str(c.get("doc_title") or ""),
                "text": "",
                "metadata": {},
            })
        items = _dedup_items(items, "item_id")
        audit["candidate_record"] = "citations_only"
    else:
        # 候选从未落库：与「召回 0」严格区分，单独成桶
        audit["status"] = "no_candidates_recorded"
        return audit
    evids = _dedup_items(
        [it for it in prediction.get("evidences") or [] if isinstance(it, dict)],
        "evidence_id",
    )
    audit["candidates_n"] = len(items)
    audit["evidences_n"] = len(evids)

    if unit is None or gold is None:
        # 分母协议：无可机读金标单独成桶，不静默退出
        audit["status"] = "no_machine_gold"
        return audit
    audit["unit"] = unit
    audit["gold_total"] = len(gold)
    if unit == "target":
        hit, missing = _hit_missing(gold, _candidate_target_ids(items, ()))
        sec_hit, _ = _hit_missing(gold, _candidate_target_ids(evids, ("evidence_id",)))
    elif unit == "doc":
        hit, missing = _hit_missing(gold, _candidate_doc_ids(items))
        sec_hit, _ = _hit_missing(gold, _candidate_doc_ids(evids))
    else:  # matter
        cand, source = candidate_matters(items, matter_resolver)
        hit, missing = _hit_missing(gold, cand)
        sec_cand, _ = candidate_matters(evids, matter_resolver)
        sec_hit, _ = _hit_missing(gold, sec_cand)
        audit["matter_source"] = source
    audit["hit"] = hit
    audit["missing"] = missing
    audit["recall"] = round(hit / len(gold), 4) if gold else None
    if evids:
        audit["secondary"] = {"hit": sec_hit, "recall": round(sec_hit / len(gold), 4)}
    return audit


def compute_audit(
    prediction: Any, question: Dict[str, Any], matter_resolver: Optional[MatterResolver] = None
) -> Dict[str, Any]:
    """单题对账。任何异常自兜底为 {"status": "audit_error"}，绝不影响评测 run。"""
    try:
        return _compute_audit(prediction, question, matter_resolver)
    except Exception as exc:  # noqa: BLE001
        return {"status": "audit_error", "error": str(exc)}


def summarize_audits(audits: List[Any]) -> Dict[str, Any]:
    """run 级聚合：_compute_summary 与 CLI 报告共用（单一真相源）。"""
    recalls: List[float] = []
    full = gap = no_gold = errors = no_record = other = 0
    for a in audits:
        if not isinstance(a, dict):
            continue
        st = a.get("status")
        if st == "audit_error":
            errors += 1
        elif st == "no_machine_gold":
            no_gold += 1
        elif st == "no_candidates_recorded":
            no_record += 1
        elif st == "ok" and a.get("gold_total"):
            if a["hit"] < a["gold_total"]:
                gap += 1
            else:
                full += 1
            if a.get("recall") is not None:
                recalls.append(float(a["recall"]))
        else:
            other += 1
    audited = len(recalls)
    return {
        "audited": audited,
        "full_recall": full,
        "with_gap": gap,
        "mean_recall": round(sum(recalls) / audited, 4) if audited else None,
        "no_machine_gold": no_gold,
        "no_candidates_recorded": no_record,
        "audit_error": errors,
        "other": other,
    }
