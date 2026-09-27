"""表格感知检索器。"""
import os
import re
import threading
from collections import OrderedDict
from typing import List, Optional, Sequence

from docs_core.models.types import (
    CanonicalTable,
    TABLE_TYPE_HYBRID,
    TABLE_TYPE_MAPPING_ENUM,
    TABLE_TYPE_NUMERIC_DENSE,
    TABLE_TYPE_TEXT_DENSE,
)
from docs_core.step09_query.protocols.contracts import KnowledgeNode, KnowledgeQueryRequest, RetrievedItem
from docs_core.step09_query.protocols.data_port import QueryDataPort, default_query_data_port
from docs_core.step09_query.retrieval.dense_retriever import score_text
from docs_core.step09_query.retrieval.query_normalizer import extract_clause_refs, normalize_match_text, tokenize_query
from docs_core.step09_query.retrieval.sparse_retriever import score_sparse_match


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


def build_full_table_text(table: CanonicalTable) -> str:
    """将完整表格组装为一段文本：caption + title + summary + header + body"""
    parts: list[str] = []
    if table.caption:
        parts.append(table.caption)
    if table.title and table.title != table.caption:
        parts.append(table.title)
    if table.summary:
        parts.append(table.summary)
    if table.header_rows:
        header_lines = [" | ".join(normalize_cell(c) for c in row if normalize_cell(c)) for row in table.header_rows]
        parts.append(" | ".join(header_lines[0]) if len(header_lines) == 1 else "\n".join(header_lines))
    if table.body_rows:
        for row in table.body_rows:
            line = " | ".join(normalize_cell(c) for c in row if normalize_cell(c))
            if line:
                parts.append(line)
    return "\n".join(parts).strip()


# ---- 归一化打分产物按表缓存（2026-09-26 表格检索提速，观测报告 §9.3）----
# 打分与候选构建只依赖表内容、与查询无关：单元格归一化、行文本、两条 sparse/score_text
# 归一化 haystack 在旧实现里每查询重复计算百万次级（normalize_cell 631 万次/查询）。
# 这里按 (doc_id, table_id) + 内容指纹做进程内 LRU；纯记忆化，候选集与分数逐位不变。
# ANGINEER_TABLE_TEXT_CACHE=0 关闭（默认开）。
class _TableArtifacts:
    __slots__ = (
        "full_text",
        "schema_text",
        "summary_text",
        "norm_schema",
        "norm_summary",
        "rows",
        "chunks",
    )

    def __init__(
        self,
        *,
        full_text: str,
        schema_text: str,
        summary_text: str,
        norm_schema: str,
        norm_summary: str,
        rows: tuple,
        chunks: tuple,
    ) -> None:
        self.full_text = full_text
        self.schema_text = schema_text
        self.summary_text = summary_text
        self.norm_schema = norm_schema
        self.norm_summary = norm_summary
        # rows: (row_index, row_key, row_text, norm_sparse_haystack, norm_row_key_haystack)
        self.rows = rows
        # chunks: (row_index, chunk_text, norm_haystack)——sparse 与 score_text 的 haystack 同串
        self.chunks = chunks


_TABLE_ARTIFACT_CACHE: "OrderedDict[tuple, _TableArtifacts]" = OrderedDict()
_TABLE_ARTIFACT_CACHE_LOCK = threading.Lock()
_TABLE_ARTIFACT_CACHE_MAX = 8192


def _env_flag(name: str, default: str) -> bool:
    return os.environ.get(name, default).strip().lower() not in {"0", "false", "off", "no"}


def _table_text_cache_enabled() -> bool:
    return _env_flag("ANGINEER_TABLE_TEXT_CACHE", "1")


def _row_agg_enabled() -> bool:
    # 行级候选按表聚合（每表只保留最相关一行）：候选数 1.2 万→千级，融合端本就按表
    # 去重（fuse_candidates best_per_key），聚合后融合结果只增不减；但排序截断前的
    # 候选分布变化须走召回对照，故默认关。
    return _env_flag("ANGINEER_TABLE_ROW_AGG", "0")


def _table_fingerprint(table: CanonicalTable) -> tuple:
    return (
        table.version,
        table.row_count,
        table.col_count,
        len(table.header_rows),
        len(table.body_rows),
        len(table.text_chunks),
    )


def _build_table_artifacts(table: CanonicalTable) -> _TableArtifacts:
    title = table.title
    full_text = build_full_table_text(table)
    schema_text = build_schema_text(table)
    summary_text = "\n".join(part for part in [table.title, table.caption, table.summary] if part).strip()
    header_text = " | ".join(normalize_cell(cell) for row in table.header_rows for cell in row if normalize_cell(cell))
    row_entries = []
    for row_index, row in enumerate(table.body_rows):
        row_values = [normalize_cell(cell) for cell in row]
        if not any(row_values):
            continue
        row_key = row_values[0] if row_values else ""
        row_text = f"{title} | {header_text} | {' | '.join(row_values)}".strip(" |")
        row_entries.append(
            (
                row_index,
                row_key,
                row_text,
                normalize_match_text(f"{title}\n{row_text}"),
                normalize_match_text(f"{row_key}\n{row_text}") if row_key else "",
            )
        )
    chunk_entries = []
    for row_index, row_text in enumerate(table.text_chunks):
        normalized_row_text = normalize_cell(row_text)
        if not normalized_row_text:
            continue
        chunk_entries.append(
            (row_index, normalized_row_text, normalize_match_text(f"{title}\n{normalized_row_text}"))
        )
    return _TableArtifacts(
        full_text=full_text,
        schema_text=schema_text,
        summary_text=summary_text,
        norm_schema=normalize_match_text(f"{title}\n{schema_text}") if schema_text else "",
        norm_summary=normalize_match_text(f"{title}\n{summary_text}") if summary_text else "",
        rows=tuple(row_entries),
        chunks=tuple(chunk_entries),
    )


def get_table_artifacts(table: CanonicalTable) -> _TableArtifacts:
    """取表的归一化打分产物（缓存未命中时构建并入 LRU）。"""
    if not _table_text_cache_enabled():
        return _build_table_artifacts(table)
    key = (table.doc_id, table.table_id) + _table_fingerprint(table)
    with _TABLE_ARTIFACT_CACHE_LOCK:
        cached = _TABLE_ARTIFACT_CACHE.get(key)
        if cached is not None:
            _TABLE_ARTIFACT_CACHE.move_to_end(key)
            return cached
    artifacts = _build_table_artifacts(table)
    with _TABLE_ARTIFACT_CACHE_LOCK:
        _TABLE_ARTIFACT_CACHE[key] = artifacts
        while len(_TABLE_ARTIFACT_CACHE) > _TABLE_ARTIFACT_CACHE_MAX:
            _TABLE_ARTIFACT_CACHE.popitem(last=False)
    return artifacts


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
        citation_target_id=table.table_id,
        retrieval_policy=source_kind,
        metadata=metadata,
    )


# 从表格行键中构造精确查找候选（行级候选，ANGINEER_TABLE_ROW_AGG=1 时按表聚合最相关一行）。
def retrieve_row_key_candidates(
    query: str,
    query_tokens: Sequence[str],
    reference_hints: Sequence[str],
    table: CanonicalTable,
    art: _TableArtifacts,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    candidates: List[RetrievedItem] = []
    aggregate = _row_agg_enabled()
    best_score = 0.0
    best_row_index: int | None = None
    for row_index, row_key, row_text, norm_sparse, norm_st in art.rows:
        score = score_sparse_match(query, row_text, table.title, "table_qa", normalized_text=norm_sparse)
        if row_key:
            if any(hint and hint in row_key for hint in reference_hints):
                score += 8.0
            if score_text(query_tokens, row_key, row_text, normalized_haystack=norm_st, tokens_pre_normalized=True) > 0:
                score += 1.6
        if score <= 0:
            continue
        if aggregate:
            if best_row_index is None or score > best_score:
                best_score = score
                best_row_index = row_index
        else:
            candidates.append(
                build_table_item(
                    table=table,
                    doc_node=doc_node,
                    item_id=f"{table.table_id}:row-key",
                    entity_type="table_row_key",
                    text=art.full_text,
                    score=score,
                    row_index=row_index,
                    chunk_type="table_row_key",
                    source_kind="table_row_key",
                    strategy="table_row_key_v1",
                )
            )
    if aggregate and best_row_index is not None:
        candidates.append(
            build_table_item(
                table=table,
                doc_node=doc_node,
                item_id=f"{table.table_id}:row-key",
                entity_type="table_row_key",
                text=art.full_text,
                score=best_score,
                row_index=best_row_index,
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
    art: _TableArtifacts,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    schema_text = art.schema_text
    if not schema_text:
        return []
    score = score_sparse_match(query, schema_text, table.title, "table_qa", normalized_text=art.norm_schema)
    if score_text(query_tokens, table.title, schema_text, normalized_haystack=art.norm_schema, tokens_pre_normalized=True) > 0:
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
            text=art.full_text,
            score=score,
            chunk_type="table_schema",
            source_kind="table_schema",
            strategy="table_schema_v1",
        )
    ]


# 从表格的行级文本块中召回文本型表格候选（行级候选，ANGINEER_TABLE_ROW_AGG=1 时按表聚合最相关一行）。
def retrieve_text_row_candidates(
    query: str,
    query_tokens: Sequence[str],
    table: CanonicalTable,
    art: _TableArtifacts,
    doc_node: KnowledgeNode,
    *,
    mapping_mode: bool = False,
) -> List[RetrievedItem]:
    candidates: List[RetrievedItem] = []
    chunk_type = "table_mapping_row" if mapping_mode else "table_text_row"
    strategy = "table_mapping_v1" if mapping_mode else "table_text_dense_v1"
    source_kind = "table_mapping" if mapping_mode else "table_text_row"
    aggregate = _row_agg_enabled()
    best_score = 0.0
    best_row_index: int | None = None

    def emit(score: float, row_index: int) -> None:
        nonlocal best_score, best_row_index
        if aggregate:
            if best_row_index is None or score > best_score:
                best_score = score
                best_row_index = row_index
        else:
            candidates.append(
                build_table_item(
                    table=table,
                    doc_node=doc_node,
                    item_id=f"{table.table_id}:text-row",
                    entity_type=chunk_type,
                    text=art.full_text,
                    score=score,
                    row_index=row_index,
                    chunk_type=chunk_type,
                    source_kind=source_kind,
                    strategy=strategy,
                )
            )

    for row_index, chunk_text, norm_haystack in art.chunks:
        score = score_sparse_match(query, chunk_text, table.title, "table_qa", normalized_text=norm_haystack) + score_text(
            query_tokens, table.title, chunk_text, normalized_haystack=norm_haystack, tokens_pre_normalized=True
        ) * 0.5
        if mapping_mode and is_definition_style_query(query):
            score += 1.5
        if score <= 0:
            continue
        emit(score, row_index)
    if aggregate and best_row_index is not None:
        candidates.append(
            build_table_item(
                table=table,
                doc_node=doc_node,
                item_id=f"{table.table_id}:text-row",
                entity_type=chunk_type,
                text=art.full_text,
                score=best_score,
                row_index=best_row_index,
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
    art: _TableArtifacts,
    doc_node: KnowledgeNode,
) -> List[RetrievedItem]:
    summary_text = art.summary_text
    if not summary_text:
        return []
    score = score_sparse_match(query, summary_text, table.title, "table_qa", normalized_text=art.norm_summary) + score_text(
        query_tokens, table.title, summary_text, normalized_haystack=art.norm_summary, tokens_pre_normalized=True
    ) * 0.3
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
            text=art.full_text,
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


def prewarm_table_artifacts(library_id: str = "default") -> int:
    """启动预热：预构建一个库全部 canonical 表的归一化打分产物（进程内缓存常驻）。

    对齐启动预热惯例——a03984f 预热向量/FTS、c957f63 补 formula 路，表格路是第三条漏网的路：
    启动查询（「规范 设计 怎么计算 公式」等）都不触发表格分支，重启后首个 L2 查表题要付
    一次性构建成本（2026-09-26 实测 ~1s/default 库 1010 表）。失败静默返回 0，不阻断启动。
    """
    if not _table_text_cache_enabled():
        return 0
    try:
        from docs_core.docs_service import get_docs_service

        service = get_docs_service()
        nodes = [n for n in service.list_nodes(library_id) if getattr(n, "type", "") == "document"]
        count = 0
        for node in nodes:
            for table in service.list_canonical_tables(doc_id=node.id, limit=500):
                get_table_artifacts(table)
                count += 1
        return count
    except Exception:  # noqa: BLE001 — 预热不得阻断启动
        return 0


class TableRetriever:
    """按表格类型执行分流召回。"""

    def __init__(self, port: Optional[QueryDataPort] = None) -> None:
        self._port = port

    # 从 canonical tables 中做 table-aware retrieval。
    def retrieve(
        self,
        request: KnowledgeQueryRequest,
        doc_nodes: List[KnowledgeNode],
    ) -> List[RetrievedItem]:
        port = self._port or default_query_data_port()
        query_tokens = tokenize_query(request.query)
        reference_hints = extract_reference_hints(request.query)
        candidates: List[RetrievedItem] = []
        for node in doc_nodes:
            tables = port.list_canonical_tables(
                doc_id=node.id,
                keyword=None,
                limit=max(30, request.top_k * 8),
            )
            for table in tables:
                art = get_table_artifacts(table)
                if table.table_type == TABLE_TYPE_NUMERIC_DENSE:
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, art, node))
                    candidates.extend(retrieve_row_key_candidates(request.query, query_tokens, reference_hints, table, art, node))
                    if not is_numeric_lookup_query(request.query):
                        candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, art, node))
                elif table.table_type == TABLE_TYPE_TEXT_DENSE:
                    candidates.extend(retrieve_text_row_candidates(request.query, query_tokens, table, art, node))
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, art, node))
                elif table.table_type == TABLE_TYPE_MAPPING_ENUM:
                    candidates.extend(
                        retrieve_text_row_candidates(
                            request.query,
                            query_tokens,
                            table,
                            art,
                            node,
                            mapping_mode=True,
                        )
                    )
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, art, node))
                elif table.table_type == TABLE_TYPE_HYBRID:
                    candidates.extend(retrieve_schema_candidates(request.query, query_tokens, reference_hints, table, art, node))
                    candidates.extend(retrieve_row_key_candidates(request.query, query_tokens, reference_hints, table, art, node))
                    candidates.extend(retrieve_text_row_candidates(request.query, query_tokens, table, art, node))
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, art, node))
                else:
                    candidates.extend(retrieve_summary_candidate(request.query, query_tokens, reference_hints, table, art, node))
        ranked = sort_table_candidates(candidates)
        return ranked[: max(1, min(20, request.top_k * 3))]


table_retriever = TableRetriever()


__all__ = [
    "TableRetriever",
    "is_definition_style_query",
    "is_numeric_lookup_query",
    "table_retriever",
]
