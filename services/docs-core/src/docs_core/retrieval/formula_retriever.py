"""公式/计算问答专用检索器。"""
from typing import List, Sequence

from docs_core.ingest.organize.types import CanonicalBlock, CanonicalDocument
from docs_core.knowledge_service import KnowledgeNode, knowledge_service
from docs_core.query.contracts import KnowledgeQueryRequest, RetrievedItem
from docs_core.retrieval.dense_retriever import score_text
from docs_core.retrieval.query_normalizer import contains_clause_ref, extract_clause_refs, tokenize_query


# 判断问题是否在询问公式、按式计算或计算步骤。
def is_formula_query(query: str, task_type: str = "content_qa") -> bool:
    normalized_query = query or ""
    markers = ("公式", "按式", "式中", "怎么算", "怎么计算", "如何计算", "计算方法", "按什么计算")
    if any(marker in normalized_query for marker in markers):
        return True
    return task_type == "definition_qa" and "式" in normalized_query


# 判断问题是否偏向“怎么计算/按什么算”的计算型问答。
def is_calculation_query(query: str) -> bool:
    markers = ("怎么算", "怎么计算", "如何计算", "计算方法", "按什么计算", "如何确定", "如何取值")
    return any(marker in (query or "") for marker in markers)


# 清洗 block 文本，避免空白影响拼接。
def normalize_block_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


# 为公式候选构造统一 RetrievedItem。
def build_formula_item(
    *,
    item_id: str,
    entity_type: str,
    doc_node: KnowledgeNode,
    block: CanonicalBlock,
    text: str,
    score: float,
    source_kind: str,
    strategy: str,
    anchor_block_ids: Sequence[str],
) -> RetrievedItem:
    return RetrievedItem(
        item_id=item_id,
        entity_type=entity_type,
        doc_id=doc_node.id,
        title=block.section_path or doc_node.title,
        text=text,
        score=score,
        metadata={
            "page_idx": block.page_idx,
            "section_path": block.section_path,
            "source_kind": source_kind,
            "chunk_type": entity_type,
            "strategy": strategy,
            "source_block_ids": list(anchor_block_ids),
        },
    )


# 判断 block 是否值得纳入公式上下文。
def is_formula_context_block(block: CanonicalBlock, formula_block: CanonicalBlock) -> bool:
    if block.block_type not in {"paragraph", "list_item", "formula"}:
        return False
    if block.block_id == formula_block.block_id:
        return True
    return (
        block.section_path == formula_block.section_path
        or abs(int(block.page_idx or 0) - int(formula_block.page_idx or 0)) <= 1
    )


# 拼装公式附近的上下文说明，优先带出计算依据与统计口径。
def build_formula_context_text(
    blocks: Sequence[CanonicalBlock],
    center_index: int,
    query_tokens: Sequence[str],
    clause_refs: Sequence[str],
) -> tuple[str, List[str]]:
    formula_block = blocks[center_index]
    selected_texts: List[str] = []
    selected_block_ids: List[str] = []
    start_index = max(0, center_index - 4)
    end_index = min(len(blocks), center_index + 5)
    for index in range(start_index, end_index):
        block = blocks[index]
        if not is_formula_context_block(block, formula_block):
            continue
        text = normalize_block_text(block.text)
        if not text:
            continue
        if block.block_type != "formula":
            has_clause_ref = bool(clause_refs) and any(contains_clause_ref(text, ref) for ref in clause_refs)
            has_calc_marker = any(marker in text for marker in ("按式", "式中", "统计", "取值", "频率", "计算", "确定"))
            has_query_overlap = score_text(query_tokens, block.section_path, text) > 0
            if not (has_clause_ref or has_calc_marker or has_query_overlap):
                continue
        if text in selected_texts:
            continue
        selected_texts.append(text)
        selected_block_ids.append(block.block_id)
    return "\n".join(selected_texts).strip(), selected_block_ids


# 为单个公式 block 构造 block 级与上下文级候选。
def build_formula_candidates(
    query: str,
    query_tokens: Sequence[str],
    clause_refs: Sequence[str],
    blocks: Sequence[CanonicalBlock],
    index: int,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    formula_block = blocks[index]
    block_text = normalize_block_text(formula_block.text)
    if not block_text:
        return []
    calc_query = is_calculation_query(query)
    ref_query = "公式" in (query or "") or "式" in (query or "")
    exact_ref = bool(clause_refs) and any(
        contains_clause_ref(f"{formula_block.section_path}\n{block_text}", ref) for ref in clause_refs
    )
    candidates: List[RetrievedItem] = []

    block_score = score_text(query_tokens, formula_block.section_path, block_text)
    if exact_ref:
        block_score += 12.0
    if calc_query:
        block_score += 4.0
    if ref_query:
        block_score += 2.0
    if block_score > 0:
        candidates.append(
            build_formula_item(
                item_id=formula_block.block_id,
                entity_type="formula",
                doc_node=doc_node,
                block=formula_block,
                text=block_text,
                score=block_score * 0.95,
                source_kind="formula_block",
                strategy="formula_block_v1",
                anchor_block_ids=[formula_block.block_id],
            )
        )

    context_text, context_block_ids = build_formula_context_text(blocks, index, query_tokens, clause_refs)
    if context_text:
        context_score = score_text(query_tokens, formula_block.section_path, context_text)
        if exact_ref:
            context_score += 10.0
        if calc_query:
            context_score += 6.0
        if any(marker in context_text for marker in ("按式", "式中", "统计", "频率", "计算", "确定")):
            context_score += 4.0
        if context_score > 0:
            candidates.append(
                build_formula_item(
                    item_id=f"{formula_block.block_id}:context",
                    entity_type="formula_context",
                    doc_node=doc_node,
                    block=formula_block,
                    text=context_text,
                    score=context_score,
                    source_kind="formula_context",
                    strategy="formula_context_v1",
                    anchor_block_ids=context_block_ids or [formula_block.block_id],
                )
            )
    return candidates


# 从 section chunk 中补充“按式/统计/取值”类说明片段。
def build_formula_chunk_candidates(
    request: KnowledgeQueryRequest,
    document: CanonicalDocument,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    query_tokens = tokenize_query(request.query)
    clause_refs = extract_clause_refs(request.query)
    calc_query = is_calculation_query(request.query)
    candidates: List[RetrievedItem] = []
    for chunk in document.chunks:
        chunk_text = normalize_block_text(chunk.text)
        if not chunk_text:
            continue
        score = score_text(query_tokens, chunk.section_path, chunk_text)
        exact_ref = bool(clause_refs) and any(contains_clause_ref(f"{chunk.section_path}\n{chunk_text}", ref) for ref in clause_refs)
        has_calc_marker = any(marker in chunk_text for marker in ("按式", "式中", "统计", "频率", "取值", "计算", "确定"))
        if exact_ref:
            score += 8.0
        if calc_query and has_calc_marker:
            score += 5.0
        if not exact_ref and not has_calc_marker and score <= 0:
            continue
        if score <= 0:
            continue
        anchor_block_id = chunk.source_block_ids[0] if chunk.source_block_ids else chunk.chunk_id
        anchor_block = CanonicalBlock(
            block_id=anchor_block_id,
            doc_id=chunk.doc_id,
            page_idx=chunk.page_start,
            block_type="paragraph",
            text=chunk_text,
            text_clean=chunk.text_clean,
            reading_order=0,
            section_path=chunk.section_path,
            source="canonical_chunk",
        )
        candidates.append(
            build_formula_item(
                item_id=f"{chunk.chunk_id}:formula-clause",
                entity_type="formula_clause",
                doc_node=doc_node,
                block=anchor_block,
                text=chunk_text,
                score=score * 0.9,
                source_kind="formula_clause",
                strategy="formula_clause_v1",
                anchor_block_ids=chunk.source_block_ids or [anchor_block_id],
            )
        )
    return candidates


# 对公式候选按类型和分数排序。
def sort_formula_candidates(candidates: List[RetrievedItem]) -> List[RetrievedItem]:
    priority = {
        "formula_context": 5,
        "formula_clause": 4,
        "formula": 3,
    }
    return sorted(
        candidates,
        key=lambda item: (
            priority.get(item.entity_type, 1),
            float(item.score or 0.0),
            -len(item.text),
        ),
        reverse=True,
    )


class FormulaRetriever:
    """执行公式/计算类问答的专用检索。"""

    # 从 canonical document 中召回公式 block、上下文和计算依据。
    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
    ) -> List[RetrievedItem]:
        query_tokens = tokenize_query(request.query)
        clause_refs = extract_clause_refs(request.query)
        candidates: List[RetrievedItem] = []
        for node in doc_nodes:
            document = knowledge_service.get_canonical_document(node.id)
            if document is None:
                continue
            ordered_blocks = sorted(document.blocks, key=lambda item: (item.page_idx, item.reading_order))
            for index, block in enumerate(ordered_blocks):
                if block.block_type != "formula":
                    continue
                candidates.extend(
                    build_formula_candidates(
                        request.query,
                        query_tokens,
                        clause_refs,
                        ordered_blocks,
                        index,
                        node,
                    )
                )
            candidates.extend(build_formula_chunk_candidates(request, document, node))
        ranked = sort_formula_candidates(candidates)
        return ranked[: max(1, min(20, request.top_k * 3))]


formula_retriever = FormulaRetriever()


__all__ = [
    "FormulaRetriever",
    "formula_retriever",
    "is_calculation_query",
    "is_formula_query",
]
