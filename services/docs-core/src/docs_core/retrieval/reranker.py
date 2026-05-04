"""候选重排与证据充分性判断。"""
from typing import List

from docs_core.query_protocols.contracts import RetrievedItem
from docs_core.retrieval.hybrid_retriever import is_toc_candidate
from docs_core.retrieval.query_normalizer import build_query_phrases, contains_clause_ref, extract_clause_refs, normalize_match_text


# 基于长短语命中和原始分数判断证据是否足够支撑回答。
def has_sufficient_evidence(query: str, candidates: List[RetrievedItem]) -> bool:
    if not candidates:
        return False
    lead = candidates[0]
    lead_raw_text = f"{lead.title}\n{lead.text}"
    lead_text = normalize_match_text(lead_raw_text)
    lead_raw_score = float(lead.metadata.get("raw_score") or lead.score or 0.0)
    query_phrases = build_query_phrases(query)
    if any(phrase in lead_text for phrase in query_phrases):
        return True
    short_phrases = build_query_phrases(query, min_n=2, max_n=4)
    if short_phrases and any(phrase in lead_text for phrase in short_phrases):
        return True
    clause_refs = extract_clause_refs(query)
    if clause_refs and any(contains_clause_ref(lead_raw_text, ref) for ref in clause_refs):
        return True
    if str(lead.metadata.get("source_kind") or "") in {"formula_block", "formula_context", "formula_clause"} and lead_raw_score >= 3.0:
        return True
    if str(lead.metadata.get("chunk_type") or "") in {"table_row_key", "table_schema", "table_mapping_row"} and lead_raw_score >= 3.0:
        return True
    return lead_raw_score >= 8.0


# 对已融合候选做轻量重排。
def rerank_candidates(query: str, task_type: str, candidates: List[RetrievedItem]) -> List[RetrievedItem]:
    if not candidates:
        return []
    query_phrases = build_query_phrases(query)
    reranked: List[RetrievedItem] = []
    for item in candidates:
        next_item = item.model_copy(deep=True)
        bonus = 0.0
        compact_text = normalize_match_text(f"{next_item.title}\n{next_item.text}")
        if any(phrase in compact_text for phrase in query_phrases):
            bonus += 0.15
        if task_type == "table_qa" and str(next_item.metadata.get("chunk_type") or "").startswith("table_"):
            bonus += 0.10
        if task_type == "definition_qa" and next_item.entity_type in {"formula", "title", "outline_anchor"}:
            bonus += 0.10
        if str(next_item.metadata.get("source_kind") or "") in {"formula_block", "formula_context", "formula_clause"}:
            bonus += 0.12
        if task_type == "locate_qa" and str(next_item.metadata.get("chunk_type") or "") in {"outline_anchor", "title"}:
            bonus += 0.08
        if is_toc_candidate(next_item):
            bonus += 0.10 if task_type == "locate_qa" else -0.20
        next_item.rerank_score = round(float(next_item.rerank_score or 0.0) + bonus, 6)
        reranked.append(next_item)
    return sorted(
        reranked,
        key=lambda item: (
            float(item.rerank_score or 0.0),
            float(item.metadata.get("normalized_score") or 0.0),
            -len(item.text),
        ),
        reverse=True,
    )
