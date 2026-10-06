from docs_core.step06_vectors.qdrant_vector_store import QdrantVectorStore


class _StubClient:
    def __init__(self):
        self.payload_calls = []

    def count(self, collection_name, count_filter, exact):
        class _R:
            count = 7
        return _R()

    def set_payload(self, collection_name, payload, points, wait):
        self.payload_calls.append({"collection": collection_name, "payload": payload, "wait": wait})


def test_set_payload_by_docs_batches_and_payload():
    store = QdrantVectorStore(url="http://unused", collection="kb")
    stub = _StubClient()
    store._client = stub
    doc_ids = [f"doc-{i}" for i in range(300)]  # 触发 256/批 → 2 批
    total = store.set_payload_by_docs(doc_ids, "lib-new")
    assert total == 14
    assert len(stub.payload_calls) == 2
    assert all(c["payload"] == {"library_id": "lib-new"} for c in stub.payload_calls)
    assert all(c["collection"] == "kb" and c["wait"] is True for c in stub.payload_calls)


def test_set_payload_collection_override():
    store = QdrantVectorStore(url="http://unused", collection="kb")
    stub = _StubClient()
    store._client = stub
    store.set_payload_by_docs(["d1"], "lib-x", collection="evals_corpus")
    assert stub.payload_calls[0]["collection"] == "evals_corpus"
