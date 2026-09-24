"""公式/计算问答专用检索器。"""
from typing import List, Optional, Sequence

from docs_core.models.types import CanonicalBlock, CanonicalChunk
from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest, RetrievedItem
from docs_core.step09_query.protocols.data_port import QueryDataPort, default_query_data_port
from docs_core.step09_query.retrieval.dense_retriever import score_text
from docs_core.step09_query.retrieval.query_normalizer import contains_clause_ref, extract_clause_refs, extract_formula_identifiers, tokenize_query


# 公式路文档预筛：FTS 预取条数（store 侧 clamp 上限即 200）、相关文档扇出上限、
# FTS 无命中时的兜底文档数（与 sparse 兜底口径一致）
_FORMULA_FTS_LIMIT = 200
_FORMULA_DOC_FANOUT = 48
_FORMULA_FALLBACK_DOCS = 20
# 上下文构造只服务于头部公式块：候选按分排序后只取前 20 输出，
# 尾部公式块（无 query 词重合、仅吃基础分）的上下文候选本就进不了终榜
_FORMULA_CONTEXT_TOP_BLOCKS = 64


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
        citation_target_id=block.block_id,
        retrieval_policy=source_kind,
        metadata={
            "page_idx": block.page_idx,
            "section_path": block.section_path,
            "source_kind": source_kind,
            "chunk_type": entity_type,
            "strategy": strategy,
            "citation_target_id": block.block_id,
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


def count_formula_identifier_matches(query_identifiers: Sequence[str], text: str) -> int:
    """统计问句中的公式符号与候选文本中的精确标识重合数量。"""
    if not query_identifiers:
        return 0
    text_identifiers = set(extract_formula_identifiers(text))
    if not text_identifiers:
        return 0
    return sum(1 for item in query_identifiers if item in text_identifiers)


# 计算单个公式 block 的 block 级得分（build_formula_candidates 与检索预筛共用同一口径）
def score_formula_block(
    query: str,
    query_tokens: Sequence[str],
    clause_refs: Sequence[str],
    query_formula_identifiers: Sequence[str],
    formula_block: CanonicalBlock,
    block_text: str,
) -> float:
    calc_query = is_calculation_query(query)
    ref_query = "公式" in (query or "") or "式" in (query or "")
    exact_ref = bool(clause_refs) and any(
        contains_clause_ref(f"{formula_block.section_path}\n{block_text}", ref) for ref in clause_refs
    )
    block_score = score_text(query_tokens, formula_block.section_path, block_text)
    if exact_ref:
        block_score += 12.0
    if calc_query:
        block_score += 4.0
    if ref_query:
        block_score += 2.0
    formula_identifier_hits = count_formula_identifier_matches(
        query_formula_identifiers,
        f"{formula_block.section_path}\n{block_text}",
    )
    if formula_identifier_hits:
        block_score += 6.0 * formula_identifier_hits
    return block_score


# 为单个公式 block 构造 block 级与上下文级候选。
def build_formula_candidates(
    query: str,
    query_tokens: Sequence[str],
    clause_refs: Sequence[str],
    query_formula_identifiers: Sequence[str],
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
    formula_identifier_hits = count_formula_identifier_matches(
        query_formula_identifiers,
        f"{formula_block.section_path}\n{block_text}",
    )
    if formula_identifier_hits:
        block_score += 6.0 * formula_identifier_hits
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
        if formula_identifier_hits:
            context_score += 4.0 * formula_identifier_hits
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
    chunks: Sequence[CanonicalChunk],
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    query_tokens = tokenize_query(request.query)
    clause_refs = extract_clause_refs(request.query)
    query_formula_identifiers = extract_formula_identifiers(request.query)
    calc_query = is_calculation_query(request.query)
    candidates: List[RetrievedItem] = []
    for chunk in chunks:
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
        score += 4.0 * count_formula_identifier_matches(
            query_formula_identifiers,
            f"{chunk.section_path}\n{chunk_text}",
        )
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

    def __init__(self, port: Optional[QueryDataPort] = None) -> None:
        self._port = port

    # 从 canonical document 中召回公式 block、上下文和计算依据。
    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
    ) -> List[RetrievedItem]:
        port = self._port or default_query_data_port()
        node_by_id = {str(getattr(node, "id", "") or ""): node for node in (doc_nodes or [])}
        explicit_doc_ids = [d for d in (request.doc_ids or []) if d and d in node_by_id]

        # —— 文档预筛：FTS 全库一次召回确定相关文档（倒排索引，毫秒级）——
        # 原实现对全库逐文档拉全量 blocks/chunks（数百篇 × 2 表），是公式路 10s+ 的根因；
        # 现只处理 FTS 相关文档（按最佳 bm25 排序截断），显式 doc_ids 范围直接用。
        fts_hits: List[dict] = []
        if explicit_doc_ids:
            selected_ids = list(explicit_doc_ids)
            if len(selected_ids) <= 16:
                for doc_id in selected_ids:
                    fts_hits.extend(
                        port.search_chunk_fts(doc_id=doc_id, query=request.query, limit=40)
                    )
            else:
                selected_set = set(selected_ids)
                fts_hits = [
                    hit
                    for hit in port.search_chunk_fts(doc_id=None, query=request.query, limit=_FORMULA_FTS_LIMIT)
                    if str(hit.get("doc_id") or "") in selected_set
                ]
        else:
            fts_hits = port.search_chunk_fts(doc_id=None, query=request.query, limit=_FORMULA_FTS_LIMIT)
            best_score_by_doc: dict = {}
            for hit in fts_hits:
                doc_id = str(hit.get("doc_id") or "")
                if not doc_id:
                    continue
                hit_score = float(hit.get("bm25_score") or 0.0)
                if doc_id not in best_score_by_doc or hit_score < best_score_by_doc[doc_id]:
                    best_score_by_doc[doc_id] = hit_score
            ranked_doc_ids = sorted(best_score_by_doc, key=lambda d: best_score_by_doc[d])
            selected_ids = [d for d in ranked_doc_ids[:_FORMULA_DOC_FANOUT] if d in node_by_id]
            if not selected_ids:
                # FTS 无命中：退化为前 N 个节点（与 sparse 兜底口径一致），
                # 保证 FTS 索引缺失等异常下公式路不至于完全空转
                selected_ids = [
                    str(getattr(node, "id", "") or "")
                    for node in list(doc_nodes or [])[:_FORMULA_FALLBACK_DOCS]
                ]
        selected_set = set(selected_ids)

        query_tokens = tokenize_query(request.query)
        clause_refs = extract_clause_refs(request.query)
        query_formula_identifiers = extract_formula_identifiers(request.query)
        candidates: List[RetrievedItem] = []
        # —— 公式块两阶段取数（替代逐文档全量 blocks 拉取，后者是公式路 10s+ 的根因）——
        # 阶段 1：批量取「选中文档的全部公式块」打分（1 条 SQL，仅 block_type='formula' 行）；
        # 阶段 2：仅对得分 top K 的公式块按页范围拉邻近块构造上下文（±1 页覆盖 ±4 窗口）。
        formula_blocks = list(
            port.list_blocks_for_docs(
                selected_ids,
                block_types=["formula"],
                per_doc_limit=2000,
            ) or []
        )
        scored_blocks: List[tuple] = []
        for block in formula_blocks:
            block_text = normalize_block_text(block.text)
            if not block_text:
                continue
            block_score = score_formula_block(
                request.query,
                query_tokens,
                clause_refs,
                query_formula_identifiers,
                block,
                block_text,
            )
            if block_score <= 0:
                continue
            scored_blocks.append((block, block_score))
        scored_blocks.sort(
            key=lambda item: (
                -item[1],
                str(item[0].doc_id),
                int(item[0].page_idx or 0),
                int(item[0].reading_order or 0),
            )
        )
        top_blocks = scored_blocks[:_FORMULA_CONTEXT_TOP_BLOCKS]
        blocks_by_doc: dict = {}
        for block, _score in top_blocks:
            blocks_by_doc.setdefault(str(block.doc_id), []).append(block)
        for doc_id, doc_formula_blocks in blocks_by_doc.items():
            node = node_by_id.get(doc_id)
            if node is None:
                continue
            page_min = max(0, min(int(b.page_idx or 0) for b in doc_formula_blocks) - 1)
            page_max = max(int(b.page_idx or 0) for b in doc_formula_blocks) + 1
            neighbor_blocks = list(
                port.list_blocks_in_page_range(doc_id, page_min=page_min, page_max=page_max) or []
            )
            ordered_blocks = sorted(neighbor_blocks, key=lambda item: (item.page_idx, item.reading_order))
            index_by_id = {block.block_id: index for index, block in enumerate(ordered_blocks)}
            for formula_block in doc_formula_blocks:
                index = index_by_id.get(formula_block.block_id)
                if index is None:
                    continue
                candidates.extend(
                    build_formula_candidates(
                        request.query,
                        query_tokens,
                        clause_refs,
                        query_formula_identifiers,
                        ordered_blocks,
                        index,
                        node,
                    )
                )

        # —— chunk 候选：FTS 命中反查完整 chunk（替代逐文档全量 chunks 扫描）——
        fts_chunk_ids = [
            str(hit.get("chunk_id") or "")
            for hit in fts_hits
            if str(hit.get("doc_id") or "") in selected_set and str(hit.get("chunk_id") or "")
        ]
        if fts_chunk_ids:
            chunks_by_doc: dict = {}
            for chunk in port.list_chunks_by_ids(fts_chunk_ids):
                chunks_by_doc.setdefault(str(chunk.doc_id), []).append(chunk)
            for doc_id, chunks in chunks_by_doc.items():
                node = node_by_id.get(doc_id)
                if node is None:
                    continue
                candidates.extend(build_formula_chunk_candidates(request, chunks, node))

        ranked = sort_formula_candidates(candidates)
        return ranked[: max(1, min(20, request.top_k * 3))]


formula_retriever = FormulaRetriever()


__all__ = [
    "FormulaRetriever",
    "formula_retriever",
    "is_calculation_query",
    "is_formula_query",
]
