"""基于 SQLite 的轻量向量存储实现"""
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from docs_core.indexing.vector_store import VectorRecord, VectorSearchHit, VectorStore
from docs_core.ingest.store.blocks_sql_store import create_connection, resolve_knowledge_index_db_path


# 统一序列JSON 字段，保SQLite 可持久化
def _dump_json(payload: object) -> str:
    return json.dumps(payload, ensure_ascii=False)


# 统一反序列化 JSON 字段，遇到异常时返回默认值
def _load_json(payload: Optional[str], default: object) -> object:
    if not payload:
        return default
    try:
        return json.loads(payload)
    except Exception:
        return default


# 为文本生成稳定哈希，便于判断索引内容是否变化
def build_content_hash(content: str) -> str:
    return hashlib.md5((content or "").encode("utf-8")).hexdigest()


# 计算两个已归一化向量的点积相似度
def dot_similarity(left: List[float], right: List[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    return float(sum(l_value * r_value for l_value, r_value in zip(left, right)))


class SQLiteVectorStore(VectorStore):
    """把向量索引持久化`knowledge_index.sqlite`"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or resolve_knowledge_index_db_path()
        self.init_schema()

    # 打开 SQLite 连接
    def connect(self):
        return create_connection(self.db_path)

    # 初始化向量索引表结构
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS canonical_vectors (
                    record_id TEXT PRIMARY KEY,
                    doc_id TEXT NOT NULL,
                    entity_type TEXT NOT NULL,
                    entity_id TEXT NOT NULL,
                    content TEXT,
                    content_hash TEXT NOT NULL,
                    metadata_json TEXT,
                    embedding_json TEXT NOT NULL,
                    dimension INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_vectors_doc_type ON canonical_vectors(doc_id, entity_type)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_canonical_vectors_doc_entity ON canonical_vectors(doc_id, entity_id)"
            )
            conn.commit()

    # 批量写入向量记录
    def upsert_records(self, records: List[VectorRecord]) -> int:
        if not records:
            return 0
        rows = [
            (
                record.record_id,
                record.doc_id,
                record.entity_type,
                record.entity_id,
                record.content,
                record.content_hash,
                _dump_json(record.metadata),
                _dump_json(record.embedding),
                len(record.embedding),
            )
            for record in records
        ]
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO canonical_vectors (
                    record_id, doc_id, entity_type, entity_id, content, content_hash,
                    metadata_json, embedding_json, dimension
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(record_id) DO UPDATE SET
                    doc_id = excluded.doc_id,
                    entity_type = excluded.entity_type,
                    entity_id = excluded.entity_id,
                    content = excluded.content,
                    content_hash = excluded.content_hash,
                    metadata_json = excluded.metadata_json,
                    embedding_json = excluded.embedding_json,
                    dimension = excluded.dimension
                """,
                rows,
            )
            conn.commit()
        return len(rows)

    # 清理指定文档的向量记录
    def clear_document(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        sql = "DELETE FROM canonical_vectors WHERE doc_id = ?"
        params: List[object] = [doc_id]
        normalized_types = [item for item in (entity_types or []) if item]
        if normalized_types:
            placeholders = ",".join(["?"] * len(normalized_types))
            sql += f" AND entity_type IN ({placeholders})"
            params.extend(normalized_types)
        with self.connect() as conn:
            cursor = conn.execute(sql, params)
            conn.commit()
            return int(cursor.rowcount or 0)

    # 执行 SQLite 内存侧相似度检索
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        sql = """
            SELECT record_id, doc_id, entity_type, entity_id, content, metadata_json, embedding_json
            FROM canonical_vectors
            WHERE 1 = 1
        """
        params: List[object] = []
        normalized_doc_ids = [item for item in (doc_ids or []) if item]
        if normalized_doc_ids:
            placeholders = ",".join(["?"] * len(normalized_doc_ids))
            sql += f" AND doc_id IN ({placeholders})"
            params.extend(normalized_doc_ids)
        normalized_types = [item for item in (entity_types or []) if item]
        if normalized_types:
            placeholders = ",".join(["?"] * len(normalized_types))
            sql += f" AND entity_type IN ({placeholders})"
            params.extend(normalized_types)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        hits: List[VectorSearchHit] = []
        for row in rows:
            embedding = list(_load_json(row["embedding_json"], []))
            if not embedding:
                continue
            score = dot_similarity(query_embedding, embedding)
            hits.append(
                VectorSearchHit(
                    record_id=row["record_id"],
                    doc_id=row["doc_id"],
                    entity_type=row["entity_type"],
                    entity_id=row["entity_id"],
                    content=row["content"] or "",
                    score=score,
                    metadata=dict(_load_json(row["metadata_json"], {})),
                )
            )
        ranked = sorted(hits, key=lambda item: (float(item.score or 0.0), len(item.content)), reverse=True)
        return ranked[: max(1, min(200, top_k))]

    # 获取单文档的向量索引统计
    def get_document_stats(self, doc_id: str) -> Dict[str, Any]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT entity_type, COUNT(*) AS total_count, MIN(dimension) AS min_dimension, MAX(dimension) AS max_dimension
                FROM canonical_vectors
                WHERE doc_id = ?
                GROUP BY entity_type
                ORDER BY entity_type ASC
                """,
                (doc_id,),
            ).fetchall()
        by_entity_type = {
            str(row["entity_type"] or "unknown"): {
                "count": int(row["total_count"] or 0),
                "min_dimension": int(row["min_dimension"] or 0),
                "max_dimension": int(row["max_dimension"] or 0),
            }
            for row in rows
        }
        return {
            "doc_id": doc_id,
            "total_count": sum(item["count"] for item in by_entity_type.values()),
            "by_entity_type": by_entity_type,
        }


__all__ = [
    "SQLiteVectorStore",
    "build_content_hash",
    "dot_similarity",
]
