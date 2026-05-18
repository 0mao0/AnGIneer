"""融合 dense 与 sparse 候选的 hybrid 检索器。"""
from typing import Any, Dict, List, Tuple

from docs_core.query_protocols.contracts import KnowledgeQueryFilter, RetrievedItem


# 对单个来源内的候选分数做归一化。
def normalize_candidate_scores(candidates: List[RetrievedItem]) -> List[RetrievedItem]:
    if not candidates:
        return []
    max_score = max(item.score for item in candidates) or 1.0
    normalized: List[RetrievedItem] = []
    for item in candidates:
        next_item = item.model_copy(deep=True)
        next_item.metadata["raw_score"] = item.score
        next_item.metadata["normalized_score"] = round(item.score / max_score, 6)
        normalized.append(next_item)
    return normalized


# 判断当前候选是否来自目录/目次类块。
def is_toc_candidate(item: RetrievedItem) -> bool:
    section_path = str(item.metadata.get("section_path") or "")
    title = str(item.title or "")
    text = str(item.text or "")
    chunk_type = str(item.metadata.get("chunk_type") or item.entity_type or "")
    page_idx = int(item.metadata.get("page_idx", 0) or 0)
    normalized_scope = f"{section_path}\n{title}\n{text}"
    if "目次" in normalized_scope or "目录" in normalized_scope:
        return True
    if page_idx == 0 and chunk_type in {"outline_anchor", "list_procedure"}:
        return True
    return False


# 为不同来源分配第一版融合权重。
def get_source_weight(source_kind: str, task_type: str) -> float:
    is_table_task = task_type in ("table_qa", "table_explain")
    source_weights = {
        "canonical_dense": 1.30,
        "canonical_sparse": 1.30,
        "toc_dense": 1.05 if task_type == "locate_qa" else 0.18,
        "toc_sparse": 1.10 if task_type == "locate_qa" else 0.12,
        "table_row_key": 1.80 if is_table_task else 0.60,
        "table_schema": 1.50 if is_table_task else 0.50,
        "table_summary": 1.20 if is_table_task else 0.50,
        "table_text_row": 1.40 if is_table_task else 0.60,
        "table_mapping": 1.40 if is_table_task else 0.60,
    }
    return source_weights.get(source_kind, 1.0)


# 按任务类型给候选加轻量业务权重。
def get_task_type_bonus(task_type: str, item: RetrievedItem) -> float:
    chunk_type = str(item.metadata.get("chunk_type") or "")
    if is_toc_candidate(item):
        return 0.12 if task_type == "locate_qa" else -0.35
    if task_type in ("table_qa", "table_explain") and chunk_type in ("table_row_key", "table_schema", "table_summary", "table_text_row", "table_mapping_row"):
        return 0.35
    if task_type == "table_qa" and chunk_type.startswith("table_"):
        return 0.25
    if task_type == "locate_qa" and chunk_type in {"outline_anchor", "title"}:
        return 0.20
    if task_type == "definition_qa" and chunk_type in {"content", "schema_desc"}:
        return 0.10
    return 0.0


# 构造候选去重键。
def build_candidate_key(item: RetrievedItem) -> str:
    chunk_type = str(item.metadata.get("chunk_type") or "")
    source_kind = str(item.metadata.get("source_kind") or "")
    if chunk_type.startswith("table_") or source_kind.startswith("table_"):
        table_id = item.metadata.get("table_id", "") or ""
        return f"table:{table_id}" if table_id else (item.item_id or "")
    if chunk_type in {"formula_block", "formula_context", "formula_clause"} or source_kind in {"formula_block", "formula_context", "formula_clause"}:
        base_id = (item.item_id or "").rsplit(":", 1)[0]
        return f"formula:{base_id}" if base_id else (item.item_id or "")
    if item.entity_type in {"figure", "figure_caption"} or chunk_type == "figure":
        return f"figure:{item.item_id}" if item.item_id else (item.item_id or "")
    return item.item_id or f"{item.doc_id}:{item.entity_type}:{item.title}"


# 应用 metadata filter，控制 section 与页码范围。
def apply_metadata_filter(candidates: List[RetrievedItem], filters: KnowledgeQueryFilter | None) -> List[RetrievedItem]:
    if filters is None:
        return candidates
    filtered: List[RetrievedItem] = []
    for item in candidates:
        page_idx = int(item.metadata.get("page_idx", 0) or 0)
        section_path = str(item.metadata.get("section_path", "") or "")
        if filters.section_path and filters.section_path not in section_path:
            continue
        if filters.page_start is not None and page_idx < filters.page_start:
            continue
        if filters.page_end is not None and page_idx > filters.page_end:
            continue
        filtered.append(item)
    return filtered


# 在非定位问答里优先保留正文证据，目录仅作兜底候选。
def prefer_non_toc_candidates(
    candidates: List[RetrievedItem],
    task_type: str,
    top_k: int,
) -> List[RetrievedItem]:
    limit = max(1, min(20, top_k))
    if task_type == "locate_qa":
        return candidates[:limit]
    non_toc_candidates = [item for item in candidates if not is_toc_candidate(item)]
    if non_toc_candidates:
        return non_toc_candidates[:limit]
    return candidates[:limit]


# 融合多来源候选并输出最终排序结果。
def fuse_candidates(
    source_candidates: Dict[str, List[RetrievedItem]],
    task_type: str,
    top_k: int,
    filters: KnowledgeQueryFilter | None = None,
) -> Tuple[List[RetrievedItem], Dict[str, Any]]:
    fused: Dict[str, RetrievedItem] = {}
    source_debug: Dict[str, Any] = {}

    for source_kind, candidates in source_candidates.items():
        normalized = normalize_candidate_scores(candidates)
        source_weight = get_source_weight(source_kind, task_type)
        source_debug[source_kind] = {
            "input_hits": len(candidates),
            "weight": source_weight,
        }
        for item in normalized:
            normalized_score = float(item.metadata.get("normalized_score") or 0.0)
            fusion_score = normalized_score * source_weight + get_task_type_bonus(task_type, item)
            key = build_candidate_key(item)
            existing = fused.get(key)
            if existing is None:
                next_item = item.model_copy(deep=True)
                next_item.rerank_score = round(fusion_score, 6)
                next_item.metadata["fusion_score"] = round(fusion_score, 6)
                next_item.metadata["fusion_sources"] = [source_kind]
                fused[key] = next_item
                continue

            existing_score = float(existing.rerank_score or 0.0)
            merged_score = 1 - (1 - min(existing_score, 0.999999)) * (1 - min(fusion_score, 0.999999))
            existing.rerank_score = round(merged_score, 6)
            existing.metadata["fusion_score"] = round(merged_score, 6)
            existing.metadata.setdefault("fusion_sources", [])
            if source_kind not in existing.metadata["fusion_sources"]:
                existing.metadata["fusion_sources"].append(source_kind)
            is_formula_key = key.startswith("formula:")
            prefer_new = fusion_score > existing_score
            if is_formula_key and len(item.text or "") > len(existing.text or ""):
                prefer_new = True
            if prefer_new:
                existing.score = item.score
                existing.title = item.title
                existing.text = item.text
                existing.entity_type = item.entity_type
                existing.metadata.update(item.metadata)
                existing.metadata["fusion_score"] = round(merged_score, 6)
                existing.metadata["fusion_sources"] = list(dict.fromkeys(existing.metadata.get("fusion_sources", [])))

    filtered = apply_metadata_filter(list(fused.values()), filters)
    ranked = sorted(
        filtered,
        key=lambda item: (
            float(item.rerank_score or 0.0),
            float(item.metadata.get("normalized_score") or 0.0),
            -len(item.text),
        ),
        reverse=True,
    )
    preferred = prefer_non_toc_candidates(ranked, task_type, top_k)
    return preferred, {
        "sources": source_debug,
        "deduped_hits": len(fused),
        "filtered_hits": len(filtered),
        "returned_hits": len(preferred),
    }
