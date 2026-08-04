"""基于 Chroma 的向量存储实现。"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.paths import resolve_chroma_persist_dir
from docs_core.step06_vectors.vector_store import VectorRecord, VectorSearchHit, VectorStore


logger = logging.getLogger(__name__)
_DIM_MISMATCH_RE = re.compile(r"expecting embedding with dimension of (\d+), got (\d+)")


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

    # 获取已有向量的维度，用于 embedding provider 维度对齐。
    def get_existing_dimension(self) -> int:
        peek = self.collection.peek(limit=1)
        embeddings = peek.get("embeddings")
        if embeddings is not None:
            embeddings_list = list(embeddings)
            if len(embeddings_list) > 0 and len(embeddings_list[0]) > 0:
                return len(embeddings_list[0])
        return 0

    # 批量写入向量记录；集合维度不匹配时自动处理。
    def upsert_records(self, records: List[VectorRecord]) -> int:
        if not records:
            return 0
        try:
            self._upsert(records)
        except Exception as exc:
            self._handle_upsert_exception(exc, records)
        return len(records)

    def _upsert(self, records: List[VectorRecord]) -> None:
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

    # 维度不匹配：集合为空时自动重建（向量可再生，零数据损失）；
    # 集合非空时给出可操作的报错，避免静默清库。
    def _handle_upsert_exception(self, exc: Exception, records: List[VectorRecord]) -> None:
        match = _DIM_MISMATCH_RE.search(str(exc))
        if not match:
            raise
        expected_dim = int(match.group(1))
        got_dim = int(match.group(2))
        if self.collection.count() > 0:
            raise RuntimeError(
                f"向量集合 {self.collection.name} 维度不匹配（集合={expected_dim}，当前={got_dim}），"
                f"且集合中已有 {self.collection.count()} 条记录，拒绝自动重建。"
                f"请删除向量库目录（{self.persist_dir}）后重新解析，或改用与当前 embedding 一致的模型。"
            ) from exc
        logger.warning(
            "向量集合 %s 维度不匹配（集合=%d，当前=%d）且集合为空，自动重建集合",
            self.collection.name, expected_dim, got_dim,
        )
        self.client.delete_collection(name=self.collection.name)
        self.collection = self.client.get_or_create_collection(
            name=self.collection.name, metadata={"hnsw:space": "cosine"}
        )
        self._upsert(records)

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

    # 按 entity_id 删除指定记录，供增量重建使用。
    def delete_records(self, doc_id: str, entity_ids: List[str]) -> int:
        normalized_ids = [item for item in entity_ids if item]
        if not normalized_ids:
            return 0
        where: Dict[str, Any] = {"$and": [{"doc_id": doc_id}, {"entity_id": {"$in": normalized_ids}}]}
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
