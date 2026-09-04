"""基于 SQLite 的轻量向量存储实现"""
import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from docs_core.step06_vectors.vector_store import VectorRecord, VectorSearchHit, VectorStore
from docs_core.paths import resolve_knowledge_index_db_path
from docs_core.step05_sqlite_fts.store.sqlite_utils import create_connection

logger = logging.getLogger(__name__)


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


# 全量向量矩阵缓存：首次加载做分批流式构建（秒级），之后每次检索只做一次 matmul（毫秒级）。
# 任何写操作或文件变化后失效。
# 构建必须持有线程锁：并发请求同时触发冷加载会重复构建并互相争抢（并发评测实测 48s+）。
# 内存约束：不得一次性 fetchall + 整表 json.loads——全量回填后瞬时内存可达数 GB，
# 小内存机器（3.6GB VM）会直接 OOM。分批游标把峰值压到「常驻矩阵 + 单批」，
# 且常驻 rows 不再保留 embedding_json 原文。
_CACHE_BUILD_BATCH_SIZE = 8192

_VECTOR_CACHE: Dict[str, Any] = {
    "loaded_mtime": None,
    "rows": None,
    "matrix": None,
}
_CACHE_LOCK = threading.Lock()


class SQLiteVectorStore(VectorStore):
    """把向量索引持久化`knowledge_index.sqlite`"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path or resolve_knowledge_index_db_path()
        self.init_schema()

    # 打开 SQLite 连接
    def connect(self):
        return create_connection(self.db_path)

    # 加载全量向量矩阵到进程缓存（按库文件 mtime 失效检测，线程安全；分批流式构建）
    def _ensure_cache(self) -> None:
        try:
            mtime = Path(self.db_path).stat().st_mtime
        except OSError:
            mtime = None
        if _VECTOR_CACHE["loaded_mtime"] == mtime and _VECTOR_CACHE["matrix"] is not None:
            return
        with _CACHE_LOCK:
            # double-check：等待锁期间可能已被其他线程构建
            if _VECTOR_CACHE["loaded_mtime"] == mtime and _VECTOR_CACHE["matrix"] is not None:
                return
            started = time.perf_counter()
            # rows 与 canonical_vectors 全表对齐（不保留 embedding_json 原文）；
            # matrix 与 valid_idx 对齐（仅含有效向量），与旧版索引语义一致。
            rows: List[Dict[str, Any]] = []
            valid_idx: List[int] = []
            matrices: List[np.ndarray] = []
            batch_embeddings: List[List[float]] = []
            batch_valid: List[int] = []
            with self.connect() as conn:
                cursor = conn.execute(
                    """
                    SELECT record_id, doc_id, entity_type, entity_id, content, metadata_json, embedding_json
                    FROM canonical_vectors
                    """
                )
                for row in cursor:
                    rows.append({
                        "record_id": row["record_id"],
                        "doc_id": row["doc_id"],
                        "entity_type": row["entity_type"],
                        "entity_id": row["entity_id"],
                        "content": row["content"],
                        "metadata_json": row["metadata_json"],
                    })
                    embedding = _load_json(row["embedding_json"], None)
                    if embedding:
                        batch_embeddings.append(embedding)
                        batch_valid.append(len(rows) - 1)
                    if len(batch_embeddings) >= _CACHE_BUILD_BATCH_SIZE:
                        matrices.append(np.asarray(batch_embeddings, dtype=np.float32))
                        valid_idx.extend(batch_valid)
                        batch_embeddings = []
                        batch_valid = []
            if batch_embeddings:
                matrices.append(np.asarray(batch_embeddings, dtype=np.float32))
                valid_idx.extend(batch_valid)
            if matrices:
                matrix = np.vstack(matrices)
            else:
                matrix = np.empty((0, 0), dtype=np.float32)
            _VECTOR_CACHE["loaded_mtime"] = mtime
            _VECTOR_CACHE["rows"] = rows
            _VECTOR_CACHE["matrix"] = matrix
            _VECTOR_CACHE["dimension"] = matrix.shape[1] if valid_idx else 0
            _VECTOR_CACHE["valid_idx"] = valid_idx
            logger.info(
                "向量矩阵缓存已构建: rows=%d valid=%d dim=%d matrix=%.0fMB 耗时=%.2fs",
                len(rows),
                len(valid_idx),
                _VECTOR_CACHE["dimension"],
                float(matrix.nbytes) / 1024 / 1024 if matrix.size else 0.0,
                time.perf_counter() - started,
            )

    # 写操作后强制失效缓存
    def _invalidate_cache(self) -> None:
        _VECTOR_CACHE["loaded_mtime"] = None
        _VECTOR_CACHE["rows"] = None
        _VECTOR_CACHE["matrix"] = None

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
        self._invalidate_cache()
        return len(rows)

    # 获取已有向量的维度，用于 embedding provider 维度对齐。
    def get_existing_dimension(self) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT dimension FROM canonical_vectors ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
        return int(row[0]) if row and row[0] else 0

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
            self._invalidate_cache()
            return int(cursor.rowcount or 0)

    # 按 entity_id 删除增量重建前的旧向量记录
    def delete_records(self, doc_id: str, entity_ids: List[str]) -> int:
        normalized_ids = [item for item in entity_ids if item]
        if not normalized_ids:
            return 0
        placeholders = ",".join(["?"] * len(normalized_ids))
        sql = f"DELETE FROM canonical_vectors WHERE doc_id = ? AND entity_id IN ({placeholders})"
        with self.connect() as conn:
            cursor = conn.execute(sql, [doc_id, *normalized_ids])
            conn.commit()
            self._invalidate_cache()
            return int(cursor.rowcount or 0)

    # 执行 SQLite 内存侧相似度检索（全量矩阵缓存 + numpy 批量 matmul）
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        self._ensure_cache()
        rows = _VECTOR_CACHE["rows"] or []
        matrix = _VECTOR_CACHE["matrix"]
        valid_idx = _VECTOR_CACHE.get("valid_idx") or []
        if not rows or matrix is None or matrix.shape[0] == 0:
            return []
        # 维度防护：查询向量维度与缓存矩阵不一致（如历史 hash 兜底低维向量）时直接返回空
        if len(query_embedding) != matrix.shape[1]:
            return []
        # 构建过滤掩码
        normalized_doc_ids = set(item for item in (doc_ids or []) if item)
        normalized_types = set(item for item in (entity_types or []) if item)
        sel_idx: List[int] = []
        if not normalized_doc_ids and not normalized_types:
            sel_idx = valid_idx
        else:
            for i in valid_idx:
                row = rows[i]
                if normalized_doc_ids and row["doc_id"] not in normalized_doc_ids:
                    continue
                if normalized_types and row["entity_type"] not in normalized_types:
                    continue
                sel_idx.append(i)
        if not sel_idx:
            return []
        q = np.asarray(query_embedding, dtype=np.float32)
        scores = (matrix[sel_idx] @ q).tolist()
        hits: List[VectorSearchHit] = []
        for rank, i in enumerate(sel_idx):
            row = rows[i]
            hits.append(
                VectorSearchHit(
                    record_id=row["record_id"],
                    doc_id=row["doc_id"],
                    entity_type=row["entity_type"],
                    entity_id=row["entity_id"],
                    content=row["content"] or "",
                    score=scores[rank],
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
