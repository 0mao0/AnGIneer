"""基于向量索引的 dense 检索器。"""
import re
from typing import Iterable, List

from docs_core.indexing import VectorSearchHit, default_embedding_provider
from docs_core.knowledge_service import KnowledgeNode, knowledge_service
from docs_core.query.contracts import KnowledgeQueryRequest, RetrievedItem
from docs_core.retrieval.query_normalizer import contains_clause_ref, extract_clause_refs, tokenize_query


# 基于关键词重叠计算轻量业务加权，不再作为 dense 主召回逻辑。
def score_text(query_tokens: Iterable[str], title: str, content: str) -> float:
    score = 0.0
    haystack = f"{title}\n{content}".lower()
    for token in query_tokens:
        if re.fullmatch(r"\d+", token or ""):
            continue
        if token and token in haystack:
            score += 1.0
    return score


# 解析 dense 检索需要拉取的向量候选上限。
def resolve_dense_search_limit(request_top_k: int) -> int:
    return max(24, request_top_k * 8)


# 为不同类型的向量实体设置基础业务权重。
def get_entity_type_bonus(task_type: str, hit: VectorSearchHit) -> float:
    chunk_type = str(hit.metadata.get("chunk_type") or hit.entity_type or "")
    entity_type = str(hit.entity_type or "")
    if task_type == "table_qa":
        if entity_type in {"table_schema", "table_row_key"} or chunk_type.startswith("table_"):
            return 0.12
    if task_type == "definition_qa":
        if chunk_type in {"outline_anchor", "table_summary"}:
            return 0.08
        if entity_type == "formula":
            return 0.04
    if task_type == "locate_qa" and chunk_type == "outline_anchor":
        return 0.10
    return 0.0


# 用 clause/ref 和计算型提示对向量结果做轻量重排。
def score_vector_hit(
    request: KnowledgeQueryRequest,
    task_type: str,
    query_tokens: List[str],
    clause_refs: List[str],
    hit: VectorSearchHit,
) -> float:
    title = str(hit.metadata.get("title") or hit.metadata.get("section_path") or "")
    text = str(hit.metadata.get("text") or hit.content or "")
    semantic_score = max(0.0, float(hit.score or 0.0))
    score = semantic_score
    lexical_bonus = score_text(query_tokens, title, text)
    if lexical_bonus > 0:
        score += min(0.18, lexical_bonus * 0.015)
    if clause_refs and any(contains_clause_ref(f"{title}\n{text}", ref) for ref in clause_refs):
        score += 0.20
    is_calc_query = any(
        marker in (request.query or "")
        for marker in ("怎么计算", "如何计算", "计算方法", "按什么计算", "按式", "公式")
    )
    if is_calc_query and any(marker in text for marker in ("按式", "公式", "式中", "计算")):
        score += 0.08
    score += get_entity_type_bonus(task_type, hit)
    return round(score, 6)


# 把向量命中统一转换为 RetrievedItem。
def build_retrieved_item(hit: VectorSearchHit, fallback_title: str, score: float) -> RetrievedItem:
    metadata = dict(hit.metadata or {})
    metadata["vector_score"] = round(float(hit.score or 0.0), 6)
    metadata["source_kind"] = "canonical_dense"
    metadata["strategy"] = "canonical_dense_vector_v1"
    metadata.setdefault("chunk_type", hit.entity_type)
    metadata.setdefault("section_path", "")
    return RetrievedItem(
        item_id=hit.entity_id,
        entity_type=str(metadata.get("chunk_type") or hit.entity_type or "content"),
        doc_id=hit.doc_id,
        title=str(metadata.get("title") or metadata.get("section_path") or fallback_title),
        text=str(metadata.get("text") or hit.content or ""),
        score=score,
        metadata=metadata,
    )


class DenseRetriever:
    """从向量索引中召回语义相关候选。"""

    def __init__(self) -> None:
        self._embedding_provider = default_embedding_provider

    # 执行向量化 dense 检索并输出统一候选。
    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
        task_type: str,
    ) -> List[RetrievedItem]:
        if not doc_nodes:
            return []
        query_tokens = tokenize_query(request.query)
        clause_refs = extract_clause_refs(request.query)
        query_embedding = self._embedding_provider.embed_text(request.query)
        doc_title_map = {node.id: node.title for node in doc_nodes}
        vector_hits = knowledge_service.search_document_vectors(
            query_embedding,
            doc_ids=[node.id for node in doc_nodes],
            entity_types=["chunk", "table_schema", "table_row_key", "formula"],
            top_k=resolve_dense_search_limit(request.top_k),
        )
        candidates: List[RetrievedItem] = []
        seen_item_ids = set()
        for hit in vector_hits:
            score = score_vector_hit(request, task_type, query_tokens, clause_refs, hit)
            if score <= 0:
                continue
            item = build_retrieved_item(hit, doc_title_map.get(hit.doc_id, ""), score)
            dedupe_key = (item.doc_id, item.item_id, item.entity_type)
            if dedupe_key in seen_item_ids:
                continue
            seen_item_ids.add(dedupe_key)
            candidates.append(item)
        return candidates


dense_retriever = DenseRetriever()
