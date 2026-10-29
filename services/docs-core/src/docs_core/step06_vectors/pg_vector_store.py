"""pgvector 向量存储实现（KB_STACK=pg 档位的第 4 个 VectorStore）。

契约与 Qdrant 实现逐项对齐（见 vector_store.VectorStore 协议 + QdrantVectorStore 扩展方法）：
- 组隔离：``collection_name`` 列复刻 Qdrant collection；collection 缺省回退
  ``QDRANT_COLLECTION``（与 legacy 同键，语义 = 默认 collection 名）。
- 分数方向：Qdrant COSINE 返回相似度（越大越好）；pgvector ``<=>`` 返回余弦距离
  （越小越好）——``score = clamp(1 - distance, 0, 1)``。
- 破平规则：``score DESC, length(content) DESC, record_id ASC``（Qdrant 版为
  ``(score, len(content))`` 倒序 + 点 id 稳定序）。
- 维度守卫：空 embedding 跳过不计数；``strict_dimension=True`` 拒写异构维度
  （2026-09-06 生产故障防线）；表列维度由 ``KNOWLEDGE_PG_VECTOR_DIM`` 定（默认 1024）。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, Iterator, List, Optional

from .config import get_qdrant_collection
from .vector_store import VectorRecord, VectorSearchHit, VectorStore
from ..pg_support import pg_connect, vector_dimension

logger = logging.getLogger(__name__)

_MAX_TOP_K = 200
_UPSERT_BATCH = 256


def _collection_name(collection: Optional[str], default: str) -> str:
    return (collection or "").strip() or default


def _vec_literal(embedding: List[float]) -> str:
    return "[" + ",".join(repr(float(v)) for v in embedding) + "]"


class PgVectorStore(VectorStore):
    """把向量索引托管到 PostgreSQL pgvector（HNSW cosine）。"""

    def __init__(self, collection: Optional[str] = None) -> None:
        # 实例默认 collection（回退值）；与 QdrantVectorStore 同语义
        self._collection = collection or get_qdrant_collection()
        self._column_dim: Optional[int] = None

    # ---- 内部工具 ---------------------------------------------------------

    def _conn(self):
        return pg_connect()

    def _column_dimension(self) -> int:
        if self._column_dim is None:
            conn = self._conn()
            try:
                cur = conn.raw.cursor()
                cur.execute(
                    "SELECT atttypmod FROM pg_attribute "
                    "WHERE attrelid = 'vector_records'::regclass AND attname = 'embedding'"
                )
                row = cur.fetchone()
                cur.close()
                self._column_dim = int(row[0] or 0) if row else 0
            finally:
                conn.close()
        return self._column_dim

    def _expected_dim(self, collection: Optional[str] = None) -> int:
        """collection 维度（本实现全表统一列维度；未建表返回 0，对齐 Qdrant 版语义）。"""
        return self._column_dimension()

    # ---- 写入 -------------------------------------------------------------

    def upsert_records(
        self,
        records: List[VectorRecord],
        strict_dimension: bool = True,
        collection: Optional[str] = None,
    ) -> int:
        if not records:
            return 0
        name = _collection_name(collection, self._collection)
        expected = self._expected_dim(name)
        written = 0
        skipped_empty = 0
        conn = self._conn()
        try:
            for start in range(0, len(records), _UPSERT_BATCH):
                batch = records[start:start + _UPSERT_BATCH]
                rows = []
                for record in batch:
                    embedding = record.embedding or []
                    if not embedding:
                        skipped_empty += 1
                        continue
                    if strict_dimension and expected > 0 and len(embedding) != expected:
                        raise ValueError(
                            f"拒绝写入异构维度向量: collection={name} 维度={expected}, "
                            f"实际={len(embedding)}；整库换维迁移请删除并重建"
                        )
                    rows.append((
                        name,
                        record.record_id,
                        record.doc_id,
                        record.entity_type,
                        record.entity_id,
                        record.content or "",
                        record.content_hash or "",
                        json.dumps(record.metadata or {}, ensure_ascii=False),
                        _vec_literal(embedding),
                        record.library_id or "",
                    ))
                if rows:
                    conn.executemany(
                        """
                        INSERT INTO vector_records (
                            collection_name, record_id, doc_id, entity_type, entity_id,
                            content, content_hash, metadata_json, embedding, library_id
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?::vector, ?)
                        ON CONFLICT (collection_name, record_id) DO UPDATE SET
                            doc_id = excluded.doc_id,
                            entity_type = excluded.entity_type,
                            entity_id = excluded.entity_id,
                            content = excluded.content,
                            content_hash = excluded.content_hash,
                            metadata_json = excluded.metadata_json,
                            embedding = excluded.embedding,
                            library_id = excluded.library_id
                        """,
                        rows,
                    )
                    written += len(rows)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
        if skipped_empty:
            logger.info("pgvector upsert 跳过空向量 %d 条（检查 embedding provider）", skipped_empty)
        return written

    def clear_document(
        self,
        doc_id: str,
        entity_types: Optional[List[str]] = None,
        collection: Optional[str] = None,
    ) -> int:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            if entity_types:
                cur = conn.execute(
                    "DELETE FROM vector_records WHERE collection_name = ? AND doc_id = ? "
                    "AND entity_type = ANY(?)",
                    (name, doc_id, list(entity_types)),
                )
            else:
                cur = conn.execute(
                    "DELETE FROM vector_records WHERE collection_name = ? AND doc_id = ?",
                    (name, doc_id),
                )
            deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def clear_library(self, library_id: str, collection: Optional[str] = None) -> int:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM vector_records WHERE collection_name = ? AND library_id = ?",
                (name, library_id),
            )
            deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_collection(self, collection: Optional[str] = None) -> bool:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM vector_records WHERE collection_name = ?", (name,))
            deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def delete_records(
        self,
        doc_id: str,
        entity_ids: List[str],
        collection: Optional[str] = None,
    ) -> int:
        if not entity_ids:
            return 0
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            cur = conn.execute(
                "DELETE FROM vector_records WHERE collection_name = ? AND doc_id = ? "
                "AND entity_id = ANY(?)",
                (name, doc_id, list(entity_ids)),
            )
            deleted = int(cur.rowcount or 0)
            conn.commit()
            return deleted
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 检索 -------------------------------------------------------------

    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
        collection: Optional[str] = None,
    ) -> List[VectorSearchHit]:
        if not query_embedding:
            return []
        name = _collection_name(collection, self._collection)
        expected = self._expected_dim(name)
        if expected > 0 and len(query_embedding) != expected:
            # 对齐 Qdrant 版：维度不匹配直接空结果（写入侧另有 strict 校验）
            return []
        cap = max(1, min(_MAX_TOP_K, top_k))
        conditions = ["collection_name = ?"]
        query_vec = _vec_literal(list(query_embedding))
        # 占位符物理顺序：SELECT 的 <=> 最先 → WHERE 过滤 → ORDER BY <=> → LIMIT；
        # psycopg 按位置计数，embedding 需在 SELECT/ORDER BY 各传一次
        params: List[Any] = [query_vec, name]
        if doc_ids:
            conditions.append("doc_id = ANY(?)")
            params.append([str(d) for d in doc_ids if d])
        if entity_types:
            conditions.append("entity_type = ANY(?)")
            params.append([str(t) for t in entity_types if t])
        params.extend([query_vec, cap])
        sql = (
            "SELECT record_id, doc_id, entity_type, entity_id, content, metadata_json, "
            "library_id, GREATEST(0.0, LEAST(1.0, 1.0 - (embedding <=> ?::vector))) AS score "
            "FROM vector_records WHERE "
            + " AND ".join(conditions)
            + " ORDER BY embedding <=> ?::vector ASC, length(content) DESC, record_id ASC LIMIT ?"
        )
        conn = self._conn()
        try:
            rows = conn.execute(sql, params).fetchall()
        finally:
            conn.close()
        hits: List[VectorSearchHit] = []
        for row in rows:
            try:
                metadata = json.loads(row["metadata_json"] or "{}")
            except Exception:  # noqa: BLE001
                metadata = {}
            hits.append(VectorSearchHit(
                record_id=row["record_id"],
                doc_id=row["doc_id"],
                entity_type=row["entity_type"],
                entity_id=row["entity_id"],
                content=row["content"] or "",
                score=float(row["score"] or 0.0),
                metadata=metadata,
                library_id=row["library_id"] or "",
            ))
        return hits

    # ---- 统计 -------------------------------------------------------------

    def get_document_stats(self, doc_id: str, collection: Optional[str] = None) -> Dict[str, Any]:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM vector_records WHERE collection_name = ? AND doc_id = ?",
                (name, doc_id),
            ).fetchone()[0]
            by_type_rows = conn.execute(
                "SELECT entity_type, COUNT(*) AS cnt, MIN(vector_dims(embedding)) AS min_dim, "
                "MAX(vector_dims(embedding)) AS max_dim "
                "FROM vector_records WHERE collection_name = ? AND doc_id = ? "
                "GROUP BY entity_type",
                (name, doc_id),
            ).fetchall()
        finally:
            conn.close()
        return {
            "doc_id": doc_id,
            "total_count": int(total or 0),
            "by_entity_type": {
                row["entity_type"]: {
                    "count": int(row["cnt"] or 0),
                    "min_dimension": int(row["min_dim"] or 0),
                    "max_dimension": int(row["max_dim"] or 0),
                }
                for row in by_type_rows
            },
        }

    def get_global_stats(self, collection: Optional[str] = None) -> Dict[str, Any]:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            total = conn.execute(
                "SELECT COUNT(*) FROM vector_records WHERE collection_name = ?",
                (name,),
            ).fetchone()[0]
            dist_rows = conn.execute(
                "SELECT vector_dims(embedding) AS dim, COUNT(*) AS cnt "
                "FROM vector_records WHERE collection_name = ? GROUP BY vector_dims(embedding)",
                (name,),
            ).fetchall()
        finally:
            conn.close()
        expected = self._column_dimension()
        return {
            "total_rows": int(total or 0),
            "zero_dimension_rows": 0,
            "expected_dimension": expected,
            "dimension_distribution": {
                str(int(row["dim"] or 0)): int(row["cnt"] or 0) for row in dist_rows
            },
        }

    def get_existing_dimension(self, collection: Optional[str] = None) -> int:
        return self._expected_dim(collection)

    def count_points_for_doc(self, doc_id: str, collection: Optional[str] = None) -> int:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM vector_records WHERE collection_name = ? AND doc_id = ?",
                (name, doc_id),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0] or 0) if row else 0

    def set_payload_by_docs(
        self,
        doc_ids: List[str],
        payload: Dict[str, Any],
        collection: Optional[str] = None,
    ) -> int:
        """合并 payload 到指定文档的点（Qdrant set_payload 语义：merge 覆盖同名键）。"""
        if not doc_ids or not payload:
            return 0
        name = _collection_name(collection, self._collection)
        payload_json = json.dumps(payload, ensure_ascii=False)
        library_id = str(payload.get("library_id") or "")
        conn = self._conn()
        try:
            if library_id:
                cur = conn.execute(
                    "UPDATE vector_records SET metadata_json = (metadata_json::jsonb || ?::jsonb)::text, "
                    "library_id = ? WHERE collection_name = ? AND doc_id = ANY(?)",
                    (payload_json, library_id, name, list(doc_ids)),
                )
            else:
                cur = conn.execute(
                    "UPDATE vector_records SET metadata_json = (metadata_json::jsonb || ?::jsonb)::text "
                    "WHERE collection_name = ? AND doc_id = ANY(?)",
                    (payload_json, name, list(doc_ids)),
                )
            updated = int(cur.rowcount or 0)
            conn.commit()
            return updated
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ---- 中性导出通道（corpus_export_neutral 用；Qdrant 版同名方法由 scroll 实现）----

    def iter_records(self, collection: Optional[str] = None, library_id: Optional[str] = None) -> Iterator[VectorRecord]:
        """按 collection（可再按 library_id）遍历（含 embedding），供导出侧生成中性包。"""
        name = _collection_name(collection, self._collection)
        batch = 512
        last_record_id = ""
        library_clause = " AND library_id = ?" if library_id else ""
        conn = self._conn()
        try:
            while True:
                sql = (
                    "SELECT record_id, doc_id, entity_type, entity_id, content, content_hash, "
                    "metadata_json, embedding::text AS embedding_text, library_id "
                    "FROM vector_records WHERE collection_name = ? AND record_id > ? "
                    + library_clause +
                    " ORDER BY record_id ASC LIMIT ?"
                )
                params = [name, last_record_id]
                if library_id:
                    params.append(library_id)
                params.append(batch)
                rows = conn.execute(sql, params).fetchall()
                if not rows:
                    return
                for row in rows:
                    last_record_id = row["record_id"]
                    try:
                        metadata = json.loads(row["metadata_json"] or "{}")
                    except Exception:  # noqa: BLE001
                        metadata = {}
                    raw = (row["embedding_text"] or "").strip("[]")
                    embedding = [float(v) for v in raw.split(",")] if raw else []
                    yield VectorRecord(
                        record_id=row["record_id"],
                        doc_id=row["doc_id"],
                        entity_type=row["entity_type"],
                        entity_id=row["entity_id"],
                        content=row["content"] or "",
                        content_hash=row["content_hash"] or "",
                        metadata=metadata,
                        embedding=embedding,
                        library_id=row["library_id"] or "",
                    )
        finally:
            conn.close()

    def count_records(self, collection: Optional[str] = None) -> int:
        name = _collection_name(collection, self._collection)
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM vector_records WHERE collection_name = ?",
                (name,),
            ).fetchone()
        finally:
            conn.close()
        return int(row[0] or 0) if row else 0
