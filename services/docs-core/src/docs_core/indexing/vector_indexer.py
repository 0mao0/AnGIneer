"""Canonical 文档向量化索引构建器。"""
from typing import Any, Dict, List

from docs_core.indexing.embedding_provider import EmbeddingProvider, default_embedding_provider
from docs_core.indexing.sqlite_vector_store import build_content_hash
from docs_core.indexing.vector_store import VectorRecord
from docs_core.ingest.organize.types import CanonicalDocument, CanonicalTable


# 拼装表格 schema 文本，兼容 dense 检索与后续调试。
def build_table_schema_text(table: CanonicalTable) -> str:
    header_lines = [" | ".join(str(cell or "").strip() for cell in row if str(cell or "").strip()) for row in table.header_rows]
    parts = [table.title, table.caption, table.summary, *header_lines]
    return "\n".join(part for part in parts if part).strip()


# 从表格对象构造多类向量索引实体。
def build_table_vector_entities(table: CanonicalTable) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    schema_text = build_table_schema_text(table)
    if schema_text:
        entities.append(
            {
                "record_id": f"{table.doc_id}:table_schema:{table.table_id}",
                "entity_type": "table_schema",
                "entity_id": table.table_id,
                "content": schema_text,
                "metadata": {
                    "chunk_type": "table_schema",
                    "page_idx": table.page_start,
                    "section_path": table.caption or table.title,
                    "table_id": table.table_id,
                    "table_type": table.table_type,
                    "table_title": table.title,
                    "title": table.title,
                    "text": schema_text,
                    "source_kind": "canonical_table_schema",
                    "strategy": "canonical_vector_v1",
                },
            }
        )
    for row_index, row_key in enumerate(table.row_keys):
        normalized_row_key = str(row_key or "").strip()
        if not normalized_row_key:
            continue
        entities.append(
            {
                "record_id": f"{table.doc_id}:table_row_key:{table.table_id}:{row_index}",
                "entity_type": "table_row_key",
                "entity_id": f"{table.table_id}:{row_index}",
                "content": normalized_row_key,
                "metadata": {
                    "chunk_type": "table_row_key",
                    "page_idx": table.page_start,
                    "section_path": table.caption or table.title,
                    "table_id": table.table_id,
                    "table_type": table.table_type,
                    "table_title": table.title,
                    "row_index": row_index,
                    "title": table.title,
                    "text": normalized_row_key,
                    "source_kind": "canonical_table_row_key",
                    "strategy": "canonical_vector_v1",
                },
            }
        )
    return entities


# 从公式 block 构造向量索引实体。
def build_formula_vector_entities(document: CanonicalDocument) -> List[Dict[str, Any]]:
    entities: List[Dict[str, Any]] = []
    for block in document.blocks:
        if block.block_type != "formula":
            continue
        text = " ".join(part for part in [block.section_path, block.text] if part).strip()
        if not text:
            continue
        entities.append(
            {
                "record_id": f"{document.doc_id}:formula:{block.block_id}",
                "entity_type": "formula",
                "entity_id": block.block_id,
                "content": text,
                "metadata": {
                    "chunk_type": "formula",
                    "page_idx": block.page_idx,
                    "section_path": block.section_path,
                    "source_block_ids": [block.block_id],
                    "title": block.section_path,
                    "text": block.text,
                    "source_kind": "canonical_formula",
                    "strategy": "canonical_vector_v1",
                },
            }
        )
    return entities


# 从 canonical document 中构造可写入向量库的记录。
def build_vector_records(
    document: CanonicalDocument,
    provider: EmbeddingProvider | None = None,
) -> List[VectorRecord]:
    resolved_provider = provider or default_embedding_provider
    payloads: List[Dict[str, Any]] = []
    for chunk in document.chunks:
        text = " ".join(part for part in [chunk.section_path, chunk.text] if part).strip()
        if not text:
            continue
        payloads.append(
            {
                "record_id": f"{document.doc_id}:chunk:{chunk.chunk_id}",
                "entity_type": "chunk",
                "entity_id": chunk.chunk_id,
                "content": text,
                "metadata": {
                    "chunk_type": chunk.chunk_type,
                    "page_idx": chunk.page_start,
                    "section_path": chunk.section_path,
                    "source_block_ids": list(chunk.source_block_ids),
                    "title": chunk.section_path,
                    "text": chunk.text,
                    "source_kind": "canonical_chunk",
                    "strategy": "canonical_vector_v1",
                },
            }
        )
    for table in document.tables:
        payloads.extend(build_table_vector_entities(table))
    payloads.extend(build_formula_vector_entities(document))
    if not payloads:
        return []
    embeddings = resolved_provider.embed_texts([payload["content"] for payload in payloads])
    records: List[VectorRecord] = []
    for payload, embedding in zip(payloads, embeddings):
        records.append(
            VectorRecord(
                record_id=payload["record_id"],
                doc_id=document.doc_id,
                entity_type=payload["entity_type"],
                entity_id=payload["entity_id"],
                content=payload["content"],
                content_hash=build_content_hash(payload["content"]),
                metadata=payload["metadata"],
                embedding=list(embedding),
            )
        )
    return records


# 输出向量索引统计，便于 ingest 链路透出结果。
def summarize_vector_records(records: List[VectorRecord]) -> Dict[str, Any]:
    by_entity_type: Dict[str, int] = {}
    dimensions = set()
    for record in records:
        by_entity_type[record.entity_type] = by_entity_type.get(record.entity_type, 0) + 1
        if record.embedding:
            dimensions.add(len(record.embedding))
    return {
        "total_count": len(records),
        "by_entity_type": by_entity_type,
        "dimensions": sorted(dimensions),
    }


__all__ = [
    "build_vector_records",
    "summarize_vector_records",
]
