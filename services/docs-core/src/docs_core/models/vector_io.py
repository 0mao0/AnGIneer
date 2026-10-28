"""向量记录与引擎 payload 之间的统一转换（中性导出/导入共用）。

Qdrant scroll 的 payload 形状与 ``corpus_export_neutral`` 的 parquet 列、
``corpus_import_neutral`` 的输入行共用同一份字段契约：
``record_id / doc_id / entity_type / entity_id / content / content_hash /
metadata / library_id``。
"""

from __future__ import annotations

from typing import Any, Dict, List

from docs_core.step06_vectors.vector_store import VectorRecord


def record_from_point_payload(payload: Dict[str, Any], vector: List[float]) -> VectorRecord:
    """引擎 payload（Qdrant scroll / 快照解析）→ VectorRecord。"""
    metadata = payload.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
    return VectorRecord(
        record_id=str(payload.get("record_id") or ""),
        doc_id=str(payload.get("doc_id") or ""),
        entity_type=str(payload.get("entity_type") or ""),
        entity_id=str(payload.get("entity_id") or ""),
        content=str(payload.get("content") or ""),
        content_hash=str(payload.get("content_hash") or ""),
        metadata=metadata,
        embedding=[float(v) for v in (vector or [])],
        library_id=str(payload.get("library_id") or ""),
    )


def record_to_point_payload(record: VectorRecord) -> Dict[str, Any]:
    """VectorRecord → 引擎 payload 形状（与 QdrantVectorStore.upsert_records 同构）。"""
    return {
        "record_id": record.record_id,
        "doc_id": record.doc_id,
        "entity_type": record.entity_type,
        "entity_id": record.entity_id,
        "content": record.content or "",
        "content_hash": record.content_hash or "",
        "metadata": record.metadata or {},
        "library_id": record.library_id or "",
    }


__all__ = ["record_from_point_payload", "record_to_point_payload"]
