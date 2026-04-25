"""基于 Chroma 的向量存储实现。"""
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.indexing.config import resolve_chroma_persist_dir
from docs_core.indexing.vector_store import VectorRecord, VectorSearchHit, VectorStore


class ChromaVectorStore(VectorStore):
    """把向量索引持久化到 Chroma。"""

    def __init__(self, persist_dir: Optional[Path] = None, collection_name: str = "docs_core_vectors") -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError("未安装 chromadb，无法使用 ChromaVectorStore。") from exc
        self._chromadb = chromadb
        self.persist_dir = Path(persist_dir or resolve_chroma_persist_dir()).resolve()
        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.persist_dir))
        self.collection = self.client.get_or_create_collection(name=collection_name, metadata={"hnsw:space": "cosine"})

    # 批量写入向量记录。
    def upsert_records(self, records: List[VectorRecord]) -> int:
        if not records:
            return 0
        self.collection.upsert(
            ids=[record.record_id for record in records],
            embeddings=[list(record.embedding) for record in records],
            documents=[record.content for record in records],
            metadatas=[
                {
                    "doc_id": record.doc_id,
                    "entity_type": record.entity_type,
                    "entity_id": record.entity_id,
                    "content_hash": record.content_hash,
                    **record.metadata,
                }
                for record in records
            ],
        )
        return len(records)

    # 清理指定文档的向量记录。
    def clear_document(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        where: Dict[str, Any] = {"doc_id": doc_id}
        normalized_types = [item for item in (entity_types or []) if item]
        if len(normalized_types) == 1:
            where["entity_type"] = normalized_types[0]
        elif normalized_types:
            where = {"$and": [{"doc_id": doc_id}, {"entity_type": {"$in": normalized_types}}]}
        existing = self.collection.get(where=where, include=[])
        ids = list(existing.get("ids") or [])
        if ids:
            self.collection.delete(ids=ids)
        return len(ids)

    # 执行向量检索并返回 top-k 命中。
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        where_clauses: List[Dict[str, Any]] = []
        normalized_doc_ids = [item for item in (doc_ids or []) if item]
        if len(normalized_doc_ids) == 1:
            where_clauses.append({"doc_id": normalized_doc_ids[0]})
        elif normalized_doc_ids:
            where_clauses.append({"doc_id": {"$in": normalized_doc_ids}})
        normalized_types = [item for item in (entity_types or []) if item]
        if len(normalized_types) == 1:
            where_clauses.append({"entity_type": normalized_types[0]})
        elif normalized_types:
            where_clauses.append({"entity_type": {"$in": normalized_types}})
        if not where_clauses:
            where = None
        elif len(where_clauses) == 1:
            where = where_clauses[0]
        else:
            where = {"$and": where_clauses}
        result = self.collection.query(
            query_embeddings=[list(query_embedding)],
            n_results=max(1, min(200, top_k)),
            where=where,
        )
        ids = list((result.get("ids") or [[]])[0])
        distances = list((result.get("distances") or [[]])[0])
        documents = list((result.get("documents") or [[]])[0])
        metadatas = list((result.get("metadatas") or [[]])[0])
        hits: List[VectorSearchHit] = []
        for record_id, distance, document, metadata in zip(ids, distances, documents, metadatas):
            payload = dict(metadata or {})
            score = max(0.0, 1.0 - float(distance or 0.0))
            hits.append(
                VectorSearchHit(
                    record_id=str(record_id or ""),
                    doc_id=str(payload.get("doc_id") or ""),
                    entity_type=str(payload.get("entity_type") or ""),
                    entity_id=str(payload.get("entity_id") or ""),
                    content=str(document or ""),
                    score=score,
                    metadata=payload,
                )
            )
        return hits

    # 获取指定文档的向量索引统计。
    def get_document_stats(self, doc_id: str) -> Dict[str, Any]:
        result = self.collection.get(where={"doc_id": doc_id}, include=["metadatas"])
        metadatas = list(result.get("metadatas") or [])
        by_entity_type: Dict[str, Dict[str, int]] = {}
        for metadata in metadatas:
            entity_type = str((metadata or {}).get("entity_type") or "unknown")
            bucket = by_entity_type.setdefault(entity_type, {"count": 0})
            bucket["count"] += 1
        return {
            "doc_id": doc_id,
            "total_count": len(list(result.get("ids") or [])),
            "by_entity_type": by_entity_type,
        }


__all__ = ["ChromaVectorStore"]
