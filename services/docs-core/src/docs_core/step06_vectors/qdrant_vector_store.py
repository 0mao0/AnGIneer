"""基于 Qdrant 的向量存储实现（ANN 引擎，替代进程内全量矩阵缓存）。

设计要点：
- point id = uuid5(NAMESPACE_URL, record_id)：幂等 upsert，重复重建索引不产生脏数据
- payload 携带 content/metadata（与 canonical_vectors 行同语义的冗余副本，编辑触发
  重嵌入时同步更新），命中直接组装 VectorSearchHit，不做跨引擎回查
- on-disk 向量存储 + on-disk HNSW + scalar int8 量化（always_ram=False）：
  面向小内存部署机（4GB），向量与索引由 Qdrant 服务端 mmap 管理，
  客户端进程零矩阵缓存（替代 SQLiteVectorStore 的每进程全量矩阵）
- 空 embedding 记录不写入（ANN 索引无法承载零向量；SQLite 实现中这类行同样不参与检索，
  仅作占位记账，Qdrant 侧直接跳过并计数）
- qdrant-client 仅在方法内惰性导入：provider != qdrant 的环境无需安装该依赖
"""
import logging
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from docs_core.step06_vectors.config import (
    get_qdrant_api_key,
    get_qdrant_collection,
    get_qdrant_timeout,
    get_qdrant_url,
)
from docs_core.step06_vectors.vector_store import VectorRecord, VectorSearchHit, VectorStore

logger = logging.getLogger(__name__)

_POINT_PREFIX = "angineer:vector:"
_UPSERT_BATCH_SIZE = 256
_SCROLL_BATCH_SIZE = 1024
# 与 SQLiteVectorStore.search 一致的 top_k 上限
_MAX_TOP_K = 200


# record_id → Qdrant point id（确定性 UUID5，保证重复写入幂等）
def _point_id(record_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, _POINT_PREFIX + str(record_id)))


def _batched(items: List[Any], size: int) -> Iterable[List[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


class QdrantVectorStore(VectorStore):
    """把向量索引托管到 Qdrant 服务（HNSW ANN + payload 过滤下推）。"""

    def __init__(
        self,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        collection: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> None:
        self._url = (url or get_qdrant_url()).rstrip("/")
        self._api_key = api_key if api_key is not None else get_qdrant_api_key()
        self._collection = collection or get_qdrant_collection()
        self._timeout = timeout if timeout is not None else get_qdrant_timeout()
        self._client: Any = None
        self._expected_dim: Optional[int] = None

    # 惰性创建客户端：provider=qdrant 但服务未起时，错误延迟到首次使用暴露，
    # 不在构造期拖死宿主进程启动
    def _get_client(self):
        if self._client is None:
            try:
                from qdrant_client import QdrantClient
            except ImportError as exc:
                raise RuntimeError("未安装 qdrant-client，无法使用 QdrantVectorStore。") from exc
            self._client = QdrantClient(
                url=self._url,
                api_key=self._api_key or None,
                timeout=self._timeout,
            )
        return self._client

    # 返回 collection 的向量维度；collection 不存在返回 0
    def _collection_dim(self) -> int:
        if self._expected_dim is not None:
            return self._expected_dim
        client = self._get_client()
        try:
            info = client.get_collection(self._collection)
        except Exception as exc:
            message = str(exc).lower()
            if "not found" in message or "404" in message or "doesn't exist" in message:
                return 0
            raise
        params = info.config.params.vectors
        size = getattr(params, "size", None)
        if size is None and isinstance(params, dict):
            # 命名向量形态兜底（本实现不创建命名向量，防御外部手工建库）
            size = next((getattr(p, "size", 0) for p in params.values()), 0)
        self._expected_dim = int(size or 0)
        return self._expected_dim

    # 按需创建 collection（on-disk 向量 + on-disk HNSW + int8 量化 + payload 索引）
    def _ensure_collection(self, dimension: int) -> None:
        if dimension <= 0:
            return
        existing = self._collection_dim()
        if existing == dimension:
            return
        if existing > 0:
            raise ValueError(
                f"拒绝写入异构维度向量: collection 维度={existing}, 实际={dimension}；"
                "整库换维迁移请删除并重建 collection"
            )
        from qdrant_client import models

        client = self._get_client()
        client.create_collection(
            collection_name=self._collection,
            vectors_config=models.VectorParams(
                size=dimension,
                distance=models.Distance.COSINE,
                on_disk=True,
            ),
            hnsw_config=models.HnswConfigDiff(on_disk=True),
            quantization_config=models.ScalarQuantization(
                scalar=models.ScalarQuantizationConfig(
                    type=models.ScalarType.INT8,
                    quantile=0.99,
                    always_ram=False,
                )
            ),
        )
        for field_name in ("doc_id", "entity_type", "entity_id"):
            client.create_payload_index(
                collection_name=self._collection,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
            )
        self._expected_dim = dimension
        logger.info(
            "Qdrant collection 已创建: %s dim=%d (on-disk 向量/HNSW + int8 量化)",
            self._collection,
            dimension,
        )

    # 批量写入向量记录
    # strict_dimension=True 时拒写与 collection 维度不同的非空向量（空向量跳过不计）。
    # 维度混布会让全库语义检索静默瘫痪（2026-09-06 生产故障），整库换维请重建 collection。
    def upsert_records(self, records: List[VectorRecord], strict_dimension: bool = True) -> int:
        if not records:
            return 0
        from qdrant_client import models

        points: List[Any] = []
        skipped_empty = 0
        for record in records:
            embedding = record.embedding or []
            if not embedding:
                skipped_empty += 1
                continue
            points.append(
                models.PointStruct(
                    id=_point_id(record.record_id),
                    vector=embedding,
                    payload={
                        "record_id": record.record_id,
                        "doc_id": record.doc_id,
                        "entity_type": record.entity_type,
                        "entity_id": record.entity_id,
                        "content": record.content or "",
                        "content_hash": record.content_hash,
                        "metadata": record.metadata or {},
                    },
                )
            )
        if skipped_empty:
            logger.info("Qdrant 跳过空向量记录 %d 条", skipped_empty)
        if not points:
            return 0
        if strict_dimension:
            expected = self.get_existing_dimension()
            if expected > 0:
                for point in points:
                    dim = len(point.vector)
                    if dim != expected:
                        raise ValueError(
                            f"拒绝写入异构维度向量: collection 维度={expected}, 实际={dim} "
                            f"(record_id={point.payload.get('record_id')}, doc_id={point.payload.get('doc_id')})；"
                            "整库换维迁移请重建 collection"
                        )
        self._ensure_collection(len(points[0].vector))
        client = self._get_client()
        for batch in _batched(points, _UPSERT_BATCH_SIZE):
            client.upsert(collection_name=self._collection, points=batch, wait=True)
        return len(points)

    # 获取已有向量的维度，用于 embedding provider 维度对齐（collection 维度即期望维度，O(1)）
    def get_existing_dimension(self) -> int:
        return self._collection_dim()

    # 清理指定文档的向量记录
    def clear_document(self, doc_id: str, entity_types: Optional[List[str]] = None) -> int:
        if self._collection_dim() == 0:
            return 0
        from qdrant_client import models

        must: List[Any] = [
            models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))
        ]
        normalized_types = [item for item in (entity_types or []) if item]
        if normalized_types:
            must.append(
                models.FieldCondition(key="entity_type", match=models.MatchAny(any=normalized_types))
            )
        return self._delete_by_filter(models.Filter(must=must))

    # 按 entity_id 删除增量重建前的旧向量记录
    def delete_records(self, doc_id: str, entity_ids: List[str]) -> int:
        normalized_ids = [item for item in entity_ids if item]
        if not normalized_ids or self._collection_dim() == 0:
            return 0
        from qdrant_client import models

        flt = models.Filter(
            must=[
                models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id)),
                models.FieldCondition(key="entity_id", match=models.MatchAny(any=normalized_ids)),
            ]
        )
        return self._delete_by_filter(flt)

    # 先计数再删除（Qdrant delete 不返回条数）
    def _delete_by_filter(self, flt: Any) -> int:
        from qdrant_client import models

        client = self._get_client()
        count = client.count(
            collection_name=self._collection, count_filter=flt, exact=True
        ).count
        if count:
            client.delete(
                collection_name=self._collection,
                points_selector=models.FilterSelector(filter=flt),
                wait=True,
            )
        return int(count)

    # 执行 ANN 相似度检索（过滤下推到 HNSW 层）
    def search(
        self,
        query_embedding: List[float],
        *,
        doc_ids: Optional[List[str]] = None,
        entity_types: Optional[List[str]] = None,
        top_k: int = 10,
    ) -> List[VectorSearchHit]:
        if not query_embedding:
            return []
        dim = self._collection_dim()
        if dim == 0:
            return []
        # 维度防护：查询向量维度与 collection 不一致（如 hash 兜底低维向量）时直接返回空
        if len(query_embedding) != dim:
            logger.warning(
                "查询向量维度 %d 与 collection 维度 %d 不一致，返回空结果",
                len(query_embedding),
                dim,
            )
            return []
        from qdrant_client import models

        must: List[Any] = []
        normalized_doc_ids = [item for item in (doc_ids or []) if item]
        normalized_types = [item for item in (entity_types or []) if item]
        if normalized_doc_ids:
            must.append(
                models.FieldCondition(key="doc_id", match=models.MatchAny(any=normalized_doc_ids))
            )
        if normalized_types:
            must.append(
                models.FieldCondition(key="entity_type", match=models.MatchAny(any=normalized_types))
            )
        query_filter = models.Filter(must=must) if must else None
        cap = max(1, min(_MAX_TOP_K, top_k))
        client = self._get_client()
        response = client.query_points(
            collection_name=self._collection,
            query=query_embedding,
            query_filter=query_filter,
            limit=cap,
            with_payload=True,
            # int8 量化下扩大候选池再用原始向量重打分，弥补量化排序误差
            search_params=models.SearchParams(
                quantization=models.QuantizationSearchParams(oversampling=2.0, rescore=True)
            ),
        )
        hits: List[VectorSearchHit] = []
        for scored in response.points:
            payload = scored.payload or {}
            hits.append(
                VectorSearchHit(
                    record_id=str(payload.get("record_id") or ""),
                    doc_id=str(payload.get("doc_id") or ""),
                    entity_type=str(payload.get("entity_type") or ""),
                    entity_id=str(payload.get("entity_id") or ""),
                    content=str(payload.get("content") or ""),
                    score=float(scored.score),
                    metadata=dict(payload.get("metadata") or {}),
                )
            )
        # 与 SQLiteVectorStore 保持一致的破平规则：(score, content 长度) 倒序
        hits.sort(key=lambda item: (item.score, len(item.content)), reverse=True)
        return hits[:cap]

    # 获取单文档的向量索引统计（按 entity_type 聚合计数）
    def get_document_stats(self, doc_id: str) -> Dict[str, Any]:
        empty = {"doc_id": doc_id, "total_count": 0, "by_entity_type": {}}
        dim = self._collection_dim()
        if dim == 0:
            return empty
        from qdrant_client import models

        client = self._get_client()
        flt = models.Filter(
            must=[models.FieldCondition(key="doc_id", match=models.MatchValue(value=doc_id))]
        )
        by_entity_type: Dict[str, Dict[str, Any]] = {}
        offset: Any = None
        while True:
            points, offset = client.scroll(
                collection_name=self._collection,
                scroll_filter=flt,
                with_payload=["entity_type"],
                with_vectors=False,
                limit=_SCROLL_BATCH_SIZE,
                offset=offset,
            )
            for point in points:
                entity_type = str((point.payload or {}).get("entity_type") or "unknown")
                entry = by_entity_type.setdefault(
                    entity_type,
                    {"count": 0, "min_dimension": dim, "max_dimension": dim},
                )
                entry["count"] += 1
            if offset is None:
                break
        return {
            "doc_id": doc_id,
            "total_count": sum(item["count"] for item in by_entity_type.values()),
            "by_entity_type": by_entity_type,
        }

    def get_global_stats(self) -> Dict[str, Any]:
        """返回全库维度/行数概览，供启动守卫使用。"""
        dim = self._collection_dim()
        if dim == 0:
            return {
                "total_rows": 0,
                "zero_dimension_rows": 0,
                "expected_dimension": 0,
                "dimension_distribution": {},
            }
        client = self._get_client()
        total = int(client.count(collection_name=self._collection, exact=False).count)
        return {
            "total_rows": total,
            # 空向量记录不写入 Qdrant，天然不存在零维脏行
            "zero_dimension_rows": 0,
            "expected_dimension": dim,
            "dimension_distribution": {dim: total},
        }


__all__ = ["QdrantVectorStore"]
