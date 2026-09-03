"""基于 canonical SQLite 的第一版 sparse 检索器。"""
import functools
import re
from typing import List, Optional

from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest, RetrievedItem
from docs_core.step09_query.protocols.data_port import QueryDataPort, default_query_data_port
from docs_core.step09_query.retrieval.query_normalizer import (
    contains_clause_ref,
    extract_clause_refs,
    extract_query_signals,
    normalize_match_text,
    token_scoring_weight,
    tokenize_query,
)


# tokenize_query 结果缓存：score_sparse_match 对同一 query 调用上万次，避免重复分词
@functools.lru_cache(maxsize=256)
def _tokenize_cached(query: str):
    return tokenize_query(query)


# 计算偏精确匹配的 sparse 分数。
def score_sparse_match(query: str, text: str, title: str = "", task_type: str = "") -> float:
    normalized_query = normalize_match_text(query)
    normalized_text = normalize_match_text(f"{title}\n{text}")
    if not normalized_query or not normalized_text:
        return 0.0
    score = 0.0
    query_tokens = _tokenize_cached(query)
    for token in query_tokens:
        if re.fullmatch(r"\d+", token or ""):
            if task_type in ("table_qa", "table_explain") and token and token in normalized_text:
                score += 1.0
            continue
        if token and token in normalized_text:
            score += token_scoring_weight(token)
    for clause_ref in extract_clause_refs(query):
        if contains_clause_ref(f"{title}\n{text}", clause_ref):
            score += 6.0
    if normalized_query in normalized_text:
        score += 4.0
    return score


def pick_chunk_keyword(query: str, clause_refs: Optional[List[str]] = None) -> Optional[str]:
    """选择块级 LIKE 过滤关键词：条款号优先，否则取短 n-gram（2 字词），
    避免把整句问法当作 LIKE 关键词导致部分命中的条款块漏召回。"""
    if clause_refs:
        return clause_refs[0]
    tokens = [token for token in tokenize_query(query) if len(token) >= 2]
    if not tokens:
        return None
    for token in tokens:
        if len(token) == 2:
            return token
    return tokens[0]


class SparseRetriever:
    """从 canonical chunks 和 blocks 中召回偏精确候选。"""

    def __init__(self, port: Optional[QueryDataPort] = None) -> None:
        self._port = port

    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
        task_type: str,
    ) -> List[RetrievedItem]:
        port = self._port or default_query_data_port()
        candidates: List[RetrievedItem] = []
        clause_refs = extract_clause_refs(request.query)
        signals = extract_query_signals(request.query)
        explicit_doc_ids = [d for d in (request.doc_ids or []) if d]

        # —— 全库 FTS 一次召回（倒排索引，毫秒级）——
        # 先由 FTS 命中确定“相关文档集合”，避免逐文档 LIKE 全表扫。
        # doc_ids 显式限定且数量少时按文档限定；否则一次全库检索。
        fts_hits: List[dict] = []
        if explicit_doc_ids and len(explicit_doc_ids) <= 16:
            for doc_id in explicit_doc_ids:
                fts_hits.extend(
                    port.search_chunk_fts(
                        doc_id=doc_id,
                        query=request.query,
                        limit=max(40, request.top_k * 2),
                    )
                )
        else:
            fts_hits = port.search_chunk_fts(
                doc_id=None,
                query=request.query,
                limit=max(60, request.top_k * 4),
            )
        relevant_doc_ids: set = set()
        fts_chunk_ids_by_doc: Dict[str, set] = {}
        for hit in fts_hits:
            doc_id = str(hit.get("doc_id") or "")
            chunk_id = str(hit.get("chunk_id") or "")
            if doc_id:
                relevant_doc_ids.add(doc_id)
            if doc_id and chunk_id:
                fts_chunk_ids_by_doc.setdefault(doc_id, set()).add(chunk_id)

        # —— 相关文档集合（FTS 命中优先；无命中时退化为前 20 个节点）——
        node_by_id = {getattr(node, "id", ""): node for node in doc_nodes}
        relevant_nodes: List[KnowledgeNode] = [
            node_by_id[did] for did in relevant_doc_ids if did in node_by_id
        ]
        if not relevant_nodes:
            relevant_nodes = list(doc_nodes[: min(20, len(doc_nodes))])

        for node in relevant_nodes:
            page_label_map = {
                page.page_idx: page.printed_page_label
                for page in port.list_canonical_pages(node.id)
                if page.printed_page_label
            }
            target_hits = port.search_citation_targets(
                doc_id=node.id,
                query=request.query,
                limit=max(20, request.top_k * 2),
            )
            for target in target_hits:
                score = score_sparse_match(
                    request.query,
                    str(target.get("snippet") or ""),
                    str(target.get("display_title") or ""),
                    task_type,
                ) + 6.0
                target_type = str(target.get("target_type") or "")
                if signals["question_type"] == "locate_figure" and target_type == "figure":
                    score += 4.0
                if signals["question_type"] == "locate_table" and target_type == "table":
                    score += 4.0
                if signals["question_type"] == "locate_formula" and target_type == "formula":
                    score += 4.0
                candidates.append(
                    RetrievedItem(
                        item_id=str(target.get("target_id") or ""),
                        entity_type=target_type or "content",
                        doc_id=node.id,
                        title=str(target.get("display_title") or node.title),
                        text=str(target.get("snippet") or ""),
                        score=score,
                        citation_target_id=str(target.get("target_id") or ""),
                        retrieval_policy="target_sparse",
                        metadata={
                            "page_idx": target.get("page_idx"),
                            "page_label": target.get("page_label"),
                            "section_path": target.get("section_path"),
                            "source_kind": "target_sparse",
                            "chunk_type": target_type or "content",
                            "strategy": "target_sparse_v1",
                            "citation_target_id": target.get("target_id"),
                            "target_type": target_type or "content",
                        },
                    )
                )

            # —— chunk 候选：FTS 命中的 chunk 反查完整结构（只限相关文档）——
            fts_chunk_ids = fts_chunk_ids_by_doc.get(node.id) or set()
            if fts_chunk_ids:
                chunks = [
                    chunk
                    for chunk in port.list_canonical_chunks(doc_id=node.id, limit=max(40, request.top_k * 3))
                    if chunk.chunk_id in fts_chunk_ids
                ]
            else:
                chunk_keyword = pick_chunk_keyword(request.query, clause_refs)
                chunks = port.list_canonical_chunks(
                    doc_id=node.id,
                    keyword=chunk_keyword,
                    limit=max(40, request.top_k * 3),
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
                        citation_target_id=(
                            chunk.citation_targets[0].target_id
                            if chunk.citation_targets
                            else None
                        ),
                        retrieval_policy="canonical_sparse",
                        metadata={
                            "page_idx": chunk.page_start,
                            "page_label": page_label_map.get(chunk.page_start),
                            "section_path": chunk.section_path,
                            "source_kind": "canonical_sparse",
                            "chunk_type": chunk.chunk_type,
                            "strategy": "canonical_sparse_v1",
                            "citation_target_id": (
                                chunk.citation_targets[0].target_id
                                if chunk.citation_targets
                                else None
                            ),
                            "inherited_chapter": chunk.inherited_chapter,
                            "entity_tags": chunk.entity_tags,
                            "conditions": chunk.conditions,
                            "exam_tags": chunk.exam_tags,
                            "clause_id": chunk.clause_id,
                        },
                    )
                )

            chunk_keyword = pick_chunk_keyword(request.query, clause_refs)
            blocks = port.list_canonical_blocks(
                doc_id=node.id,
                keyword=chunk_keyword,
                limit=max(20, request.top_k * 3),
            )
            for block in blocks:
                # 页眉页脚/目录不参与正文检索（目录锚点走 outline_anchor chunk）
                if block.block_type in {"header_footer", "toc"}:
                    continue
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
                        citation_target_id=block.block_id,
                        retrieval_policy="canonical_sparse",
                        metadata={
                            "page_idx": block.page_idx,
                            "page_label": page_label_map.get(block.page_idx),
                            "section_path": block.section_path,
                            "source_kind": "canonical_sparse",
                            "chunk_type": block.block_type,
                            "strategy": "canonical_sparse_v1",
                            "citation_target_id": block.block_id,
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
