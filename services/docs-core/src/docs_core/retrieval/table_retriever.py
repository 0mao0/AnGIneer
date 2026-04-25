"""表格感知检索器。"""
import re
from typing import Iterable, List, Sequence

from docs_core.ingest.organize.types import CanonicalTable
from docs_core.ingest.normalize.table_semantics import (
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
)
from docs_core.knowledge_service import KnowledgeNode, knowledge_service
from docs_core.query.contracts import KnowledgeQueryRequest, RetrievedItem
from docs_core.retrieval.dense_retriever import score_text
from docs_core.retrieval.query_normalizer import extract_clause_refs, tokenize_query
from docs_core.retrieval.sparse_retriever import score_sparse_match


# 归一化表格单元格文本，避免空白干扰后续匹配。
def normalize_cell(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


# 判断问题是否更像定义、解释或枚举映射问答。
def is_definition_style_query(query: str) -> bool:
    markers = ("什么是", "定义", "含义", "解释", "表示什么", "代表什么", "是什么意思")
    return any(marker in (query or "") for marker in markers)


# 判断问题是否更像数值查找类问答。
def is_numeric_lookup_query(query: str) -> bool:
    markers = ("多少", "取多少", "什么值", "数值", "多大", "取值", "上限", "下限", "系数")
    return any(marker in (query or "") for marker in markers)


# 判断问题是否引用了结构编号，便于精确命中标题或行键。
def extract_reference_hints(query: str) -> List[str]:
    refs = list(extract_clause_refs(query))
    for match in re.findall(r"附录\s*[A-Z]", query or "", flags=re.IGNORECASE):
        normalized = " ".join(match.split()).upper()
        if normalized not in refs:
            refs.append(normalized)
    return refs


# 把表头和表格摘要拼成 schema 检索文本。
def build_schema_text(table: CanonicalTable) -> str:
    header_rows = [" | ".join(normalize_cell(cell) for cell in row if normalize_cell(cell)) for row in table.header_rows]
    parts = [table.title, table.caption, table.summary, *header_rows]
    return "\n".join(part for part in parts if part).strip()


# 为单条行文本构造统一 RetrievedItem。
def build_table_item(
    *,
    table: CanonicalTable,
    doc_node: KnowledgeNode,
    item_id: str,
    entity_type: str,
    text: str,
    score: float,
    row_index: int | None = None,
    chunk_type: str | None = None,
    source_kind: str = "table_aware",
    strategy: str = "table_aware_v1",
) -> RetrievedItem:
    metadata = {
        "page_idx": table.page_start,
        "section_path": table.caption or table.title,
        "source_kind": source_kind,
        "chunk_type": chunk_type or entity_type,
        "strategy": strategy,
        "table_id": table.table_id,
        "table_type": table.table_type,
        "table_title": table.title,
    }
    if row_index is not None:
        metadata["row_index"] = row_index
    return RetrievedItem(
        item_id=item_id,
        entity_type=entity_type,
        doc_id=table.doc_id,
        title=table.title or doc_node.title,
        text=text,
        score=score,
        metadata=metadata,
    )


# 从表格行键中构造精确查找候选。
def retrieve_row_key_candidates(
    query: str,
    query_tokens: Sequence[str],
    reference_hints: Sequence[str],
    table: CanonicalTable,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    candidates: List[RetrievedItem] = []
    header_text = " | ".join(normalize_cell(cell) for row in table.header_rows for cell in row if normalize_cell(cell))
    for row_index, row in enumerate(table.body_rows):
        row_values = [normalize_cell(cell) for cell in row]
        if not any(row_values):
            continue
        row_key = row_values[0] if row_values else ""
        row_text = f"{table.title} | {header_text} | {' | '.join(row_values)}".strip(" |")
        score = score_sparse_match(query, row_text, table.title)
        if row_key:
            if any(hint and hint in row_key for hint in reference_hints):
                score += 8.0
            if score_text(query_tokens, row_key, row_text) > 0:
                score += 1.6
        if score <= 0:
            continue
        candidates.append(
            build_table_item(
                table=table,
                doc_node=doc_node,
                item_id=f"{table.table_id}:row-key:{row_index}",
                entity_type="table_row_key",
                text=row_text,
                score=score,
                row_index=row_index,
                chunk_type="table_row_key",
                source_kind="table_row_key",
                strategy="table_row_key_v1",
            )
        )
    return candidates


# 从表头与摘要中构造 schema 检索候选。
def retrieve_schema_candidates(
    query: str,
    query_tokens: Sequence[str],
    reference_hints: Sequence[str],
    table: CanonicalTable,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    schema_text = build_schema_text(table)
    if not schema_text:
        return []
    score = score_sparse_match(query, schema_text, table.title)
    if score_text(query_tokens, table.title, schema_text) > 0:
        score += 1.2
    if any(hint and hint in schema_text for hint in reference_hints):
        score += 6.0
    if score <= 0:
        return []
    return [
        build_table_item(
            table=table,
            doc_node=doc_node,
            item_id=f"{table.table_id}:schema",
            entity_type="table_schema",
            text=schema_text,
            score=score,
            chunk_type="table_schema",
            source_kind="table_schema",
            strategy="table_schema_v1",
        )
    ]


# 从表格的行级文本块中召回文本型表格候选。
def retrieve_text_row_candidates(
    query: str,
    query_tokens: Sequence[str],
    table: CanonicalTable,
    doc_node: KnowledgeNode,
    *,
    mapping_mode: bool = False,
) -> List[RetrievedItem]:
    candidates: List[RetrievedItem] = []
    chunk_type = "table_mapping_row" if mapping_mode else "table_text_row"
    strategy = "table_mapping_v1" if mapping_mode else "table_text_dense_v1"
    source_kind = "table_mapping" if mapping_mode else "table_text_row"
    for row_index, row_text in enumerate(table.text_chunks):
        normalized_row_text = normalize_cell(row_text)
        if not normalized_row_text:
            continue
        score = score_sparse_match(query, normalized_row_text, table.title) + score_text(query_tokens, table.title, normalized_row_text) * 0.5
        if mapping_mode and is_definition_style_query(query):
            score += 1.5
        if score <= 0:
            continue
        candidates.append(
            build_table_item(
                table=table,
                doc_node=doc_node,
                item_id=f"{table.table_id}:text-row:{row_index}",
                entity_type=chunk_type,
                text=normalized_row_text,
                score=score,
                row_index=row_index,
                chunk_type=chunk_type,
                source_kind=source_kind,
                strategy=strategy,
            )
        )
    return candidates


# 从整表摘要中构造回退候选。
def retrieve_summary_candidate(
    query: str,
    query_tokens: Sequence[str],
    reference_hints: Sequence[str],
    table: CanonicalTable,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    summary_text = "\n".join(part for part in [table.title, table.caption, table.summary] if part).strip()
    if not summary_text:
        return []
    score = score_sparse_match(query, summary_text, table.title) + score_text(query_tokens, table.title, summary_text) * 0.3
    if any(hint and hint in summary_text for hint in reference_hints):
        score += 4.0
    if score <= 0:
        return []
    return [
        build_table_item(
            table=table,
            doc_node=doc_node,
            item_id=f"{table.table_id}:summary",
            entity_type="table_summary",
            text=summary_text,
            score=score,
            chunk_type="table_summary",
            source_kind="table_summary",
            strategy="table_summary_v1",
        )
    ]


# 对表格候选按业务优先级与分数排序。
def sort_table_candidates(candidates: List[RetrievedItem]) -> List[RetrievedItem]:
    priority = {
        "table_row_key": 5,
        "table_schema": 4,
        "table_mapping_row": 4,
        "table_text_row": 3,
        "table_summary": 2,
    }
    return sorted(
        candidates,
        key=lambda item: (
            priority.get(str(item.metadata.get("chunk_type") or item.entity_type or ""), 1),
            float(item.score or 0.0),
            -len(item.text),
        ),
        reverse=True,
    )


class TableRetriever:
    """按表格类型执行分流召回。"""

    # 从 canonical tables 中做 table-aware retrieval。
    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
    ) -> List[RetrievedItem]:
        query_tokens = tokenize_query(request.query)
        reference_hints = extract_reference_hints(request.query)
        candidates: List[RetrievedItem] = []
        for node in doc_nodes:
            tables = knowledge_service.list_canonical_tables(
                doc_id=node.id,
                keyword=None,
                limit=max(30, request.top_k * 8),
            )
            for table in tables:
                if table.table_type == TABLE_TYPE_NUMERIC_DENSE:
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, node))
                    candidates.extend(retrieve_row_key_candidates(request.query, query_tokens, reference_hints, table, node))
                    if not is_numeric_lookup_query(request.query):
                        candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, node))
                elif table.table_type == TABLE_TYPE_TEXT_DENSE:
                    candidates.extend(retrieve_text_row_candidates(request.query, query_tokens, table, node))
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, node))
                elif table.table_type == TABLE_TYPE_MAPPING_ENUM:
                    candidates.extend(
                        retrieve_text_row_candidates(
                            request.query,
                            query_tokens,
                            table,
                            node,
                            mapping_mode=True,
                        )
                    )
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, node))
                elif table.table_type == TABLE_TYPE_HYBRID:
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, node))
                    candidates.extend(retrieve_row_key_candidates(request.query, query_tokens, reference_hints, table, node))
                    candidates.extend(retrieve_text_row_candidates(request.query, query_tokens, table, node))
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, node))
                else:
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, node))
        ranked = sort_table_candidates(candidates)
        return ranked[: max(1, min(20, request.top_k * 3))]


table_retriever = TableRetriever()


__all__ = [
    "TableRetriever",
    "is_definition_style_query",
    "is_numeric_lookup_query",
    "table_retriever",
]
