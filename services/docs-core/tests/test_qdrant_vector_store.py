"""QdrantVectorStore 集成测试。

需要本地可连的 Qdrant（默认 http://localhost:6333，可用 QDRANT_TEST_URL 覆盖）；
不可达时整组 skip（CI 无 docker 时安全降级）。每个测试会话使用独立 collection，
结束即删除，不污染开发库。
"""
import os
import uuid

import numpy as np
import pytest

from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore
from docs_core.step06_vectors.vector_store import VectorRecord

TEST_URL = os.environ.get("QDRANT_TEST_URL", "http://localhost:6333")


def _qdrant_reachable() -> bool:
    try:
        from qdrant_client import QdrantClient

        QdrantClient(url=TEST_URL, timeout=3).get_collections()
        return True
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _qdrant_reachable(), reason="Qdrant 不可达，跳过集成测试")


@pytest.fixture()
def store():
    collection = f"test_vectors_{uuid.uuid4().hex[:12]}"
    store = QdrantVectorStore(url=TEST_URL, collection=collection, timeout=10)
    yield store
    try:
        store._get_client().delete_collection(collection)
    except Exception:
        pass


def _record(record_id: str, doc_id: str, entity_type: str, embedding, content: str) -> VectorRecord:
    return VectorRecord(
        record_id=record_id,
        doc_id=doc_id,
        entity_type=entity_type,
        entity_id=record_id,
        content=content,
        metadata={"doc_id": doc_id, "entity_type": entity_type, "tag": record_id},
        embedding=embedding,
    )


def _random_records(n, dim, rng):
    records = []
    for i in range(n):
        vec = rng.standard_normal(dim).tolist()
        doc = f"doc-{i % 5}"
        etype = "chunk" if i % 3 else "formula"
        records.append(_record(f"rec-{i:04d}", doc, etype, vec, f"内容-{i}-" + "x" * (i % 11)))
    return records


def test_upsert_and_search_roundtrip(store):
    rng = np.random.default_rng(7)
    records = _random_records(60, 32, rng)
    assert store.upsert_records(records) == 60
    query = records[0].embedding
    hits = store.search(query, top_k=5)
    assert hits
    # 自查询应命中自身（cosine 相似度 ~1.0）
    assert hits[0].record_id == records[0].record_id
    assert hits[0].score == pytest.approx(1.0, abs=1e-3)
    # payload 字段完整回带
    assert hits[0].content == records[0].content
    assert hits[0].metadata["tag"] == records[0].record_id


def test_upsert_idempotent(store):
    rng = np.random.default_rng(11)
    records = _random_records(20, 16, rng)
    store.upsert_records(records)
    store.upsert_records(records)  # 同 record_id 重复写入
    stats = store.get_global_stats()
    assert stats["total_rows"] == 20


def test_filters(store):
    rng = np.random.default_rng(13)
    records = _random_records(60, 16, rng)
    store.upsert_records(records)
    query = rng.standard_normal(16).tolist()
    hits = store.search(query, doc_ids=["doc-0", "doc-2"], top_k=10)
    assert hits and all(hit.doc_id in {"doc-0", "doc-2"} for hit in hits)
    hits = store.search(query, entity_types=["formula"], top_k=10)
    assert hits and all(hit.entity_type == "formula" for hit in hits)
    hits = store.search(query, doc_ids=["doc-1"], entity_types=["chunk"], top_k=50)
    assert hits and all(hit.doc_id == "doc-1" and hit.entity_type == "chunk" for hit in hits)


def test_clear_document(store):
    rng = np.random.default_rng(17)
    records = _random_records(40, 16, rng)
    store.upsert_records(records)
    removed = store.clear_document("doc-0")
    assert removed == 8  # 40 条 / 5 个 doc
    stats = store.get_document_stats("doc-0")
    assert stats["total_count"] == 0
    assert store.get_global_stats()["total_rows"] == 32
    # entity_types 限定清理
    removed = store.clear_document("doc-1", entity_types=["chunk"])
    remaining = store.get_document_stats("doc-1")
    assert removed > 0
    assert remaining["by_entity_type"].get("chunk") is None
    assert remaining["total_count"] > 0


def test_delete_records_by_entity_ids(store):
    rng = np.random.default_rng(19)
    records = _random_records(20, 16, rng)
    store.upsert_records(records)
    target_ids = [rec.entity_id for rec in records[:3]]
    removed = store.delete_records("doc-0", target_ids)
    kept = [rec for rec in records[:3] if rec.doc_id == "doc-0"]
    assert removed == len(kept)
    stats = store.get_global_stats()
    assert stats["total_rows"] == 20 - len(kept)


def test_get_document_stats_grouping(store):
    rng = np.random.default_rng(23)
    records = _random_records(30, 16, rng)
    store.upsert_records(records)
    stats = store.get_document_stats("doc-0")
    assert stats["doc_id"] == "doc-0"
    assert stats["total_count"] == 6
    assert set(stats["by_entity_type"]) == {"chunk", "formula"}
    for entry in stats["by_entity_type"].values():
        assert entry["min_dimension"] == entry["max_dimension"] == 16


def test_dimension_guard_rejects_hetero(store):
    store.upsert_records([_record("a", "doc-x", "chunk", np.zeros(16).tolist(), "内容")])
    assert store.get_existing_dimension() == 16
    with pytest.raises(ValueError, match="异构维度"):
        store.upsert_records([_record("bad", "doc-x", "chunk", np.zeros(64).tolist(), "内容")])


def test_empty_embedding_skipped(store):
    assert store.upsert_records([_record("empty-1", "doc-e", "chunk", [], "空向量")]) == 0
    store.upsert_records([
        _record("empty-2", "doc-e", "chunk", [], "空向量2"),
        _record("ok-1", "doc-e", "chunk", [1.0, 0.0, 0.0], "正常"),
    ])
    assert store.get_global_stats()["total_rows"] == 1
    hits = store.search([1.0, 0.0, 0.0], top_k=5)
    assert [hit.record_id for hit in hits] == ["ok-1"]


def test_empty_collection_returns_empty(store):
    assert store.search([1.0, 0.0], top_k=5) == []
    assert store.get_existing_dimension() == 0
    assert store.get_document_stats("doc-none")["total_count"] == 0
    assert store.clear_document("doc-none") == 0


def test_dimension_mismatch_query_returns_empty(store):
    store.upsert_records([_record("a", "doc-x", "chunk", [1.0] * 16, "内容")])
    assert store.search([1.0] * 64, top_k=5) == []
