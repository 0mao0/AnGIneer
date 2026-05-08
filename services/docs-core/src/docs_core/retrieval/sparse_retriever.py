"""基于 canonical SQLite 的第一版 sparse 检索器。"""
import re
from typing import List

from docs_core.knowledge_service import KnowledgeNode, knowledge_service
from docs_core.query_protocols.contracts import KnowledgeQueryRequest, RetrievedItem
from docs_core.retrieval.query_normalizer import (
    contains_clause_ref,
    extract_clause_refs,
    normalize_match_text,
    tokenize_query,
)


# 计算偏精确匹配的 sparse 分数。
def score_sparse_match(query: str, text: str, title: str = "", task_type: str = "") -> float:
    normalized_query = normalize_match_text(query)
    normalized_text = normalize_match_text(f"{title}\n{text}")
    if not normalized_query or not normalized_text:
        return 0.0
    score = 0.0
    query_tokens = tokenize_query(query)
    for token in query_tokens:
        if re.fullmatch(r"\d+", token or ""):
            if task_type in ("table_qa", "table_explain") and token and token in normalized_text:
                score += 1.0
            continue
        if token and token in normalized_text:
            score += 1.0
    for clause_ref in extract_clause_refs(query):
        if contains_clause_ref(f"{title}\n{text}", clause_ref):
            score += 6.0
    if normalized_query in normalized_text:
        score += 4.0
    return score


class SparseRetriever:
    """从 canonical chunks 和 blocks 中召回偏精确候选。"""

    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
        task_type: str,
    ) -> List[RetrievedItem]:
        candidates: List[RetrievedItem] = []
        clause_refs = extract_clause_refs(request.query)
        for node in doc_nodes:
            chunk_keyword = clause_refs[0] if clause_refs else next((token for token in tokenize_query(request.query) if len(token) >= 2), None)
            chunks = knowledge_service.list_canonical_chunks(
                doc_id=node.id,
                keyword=chunk_keyword,
                limit=max(40, request.top_k * 10),
            )
            for chunk in chunks:
                score = score_sparse_match(request.query, chunk.text, chunk.section_path, task_type)
                if score <= 0:
                    continue
                if clause_refs and any(contains_clause_ref(f"{chunk.section_path}\n{chunk.text}", ref) for ref in clause_refs):
                    score += 8.0
                if task_type == "definition_qa" and chunk.chunk_type in {"outline_anchor", "table_summary"}:
                    score += 1.0
                candidates.append(
                    RetrievedItem(
                        item_id=chunk.chunk_id,
                        entity_type=chunk.chunk_type,
                        doc_id=node.id,
                        title=chunk.section_path or node.title,
                        text=chunk.text,
                        score=score,
                        metadata={
                            "page_idx": chunk.page_start,
                            "section_path": chunk.section_path,
                            "source_kind": "canonical_sparse",
                            "chunk_type": chunk.chunk_type,
                            "strategy": "canonical_sparse_v1",
                            "inherited_chapter": chunk.inherited_chapter,
                            "entity_tags": chunk.entity_tags,
                            "conditions": chunk.conditions,
                            "exam_tags": chunk.exam_tags,
                            "clause_id": chunk.clause_id,
                        },
                    )
                )

            blocks = knowledge_service.list_canonical_blocks(
                doc_id=node.id,
                keyword=chunk_keyword,
                limit=max(20, request.top_k * 6),
            )
            for block in blocks:
                score = score_sparse_match(request.query, block.text, block.section_path, task_type)
                if score <= 0:
                    continue
                if clause_refs and any(contains_clause_ref(f"{block.section_path}\n{block.text}", ref) for ref in clause_refs):
                    score += 8.0
                if task_type == "locate_qa" and block.block_type == "title":
                    score += 1.0
                if task_type == "definition_qa" and block.block_type in {"formula", "title"}:
                    score += 1.5
                candidates.append(
                    RetrievedItem(
                        item_id=block.block_id,
                        entity_type=block.block_type,
                        doc_id=node.id,
                        title=block.section_path or node.title,
                        text=block.text,
                        score=score * 0.85,
                        metadata={
                            "page_idx": block.page_idx,
                            "section_path": block.section_path,
                            "source_kind": "canonical_sparse",
                            "chunk_type": block.block_type,
                            "strategy": "canonical_sparse_v1",
                            "inherited_chapter": block.inherited_chapter,
                            "entity_tags": block.entity_tags,
                            "conditions": block.conditions,
                            "exam_tags": block.exam_tags,
                            "clause_id": block.clause_id,
                        },
                    )
                )
        return candidates


sparse_retriever = SparseRetriever()
